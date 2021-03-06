from __future__ import annotations

import typing as ty

if ty.TYPE_CHECKING:
   from .context import ConfigCtx

import yaml
import pathlib as pl
import collections as clc
import contextlib
import asyncio.locks
import aurcore

CONFIG_DIR = pl.Path("./.fluxconf/")
CONFIG_DIR.mkdir(exist_ok=True)

CACHED_CONFIGS = 100


def merge_config(template, config, path=None):
   if path is None: path = []
   changed = False
   for key in config:
      if key in template:
         if isinstance(template[key], dict) and isinstance(config[key], dict):
            _, changed_ = merge_config(template[key], config[key], path + [str(key)])
            changed = changed or changed_
         elif template[key] == config[key]:
            pass  # same leaf value
         else:
            template[key] = config[key]
            changed = True

      # else:
      #    template[key] = config[key]
   return template, changed

# @ext.AutoRepr
class Config(metaclass=aurcore.util.Singleton):

   def __init__(self, admin_id: int, name=""):
      self.config_dir = CONFIG_DIR / name
      self.config_dir.mkdir(exist_ok=True)
      if not (self.config_dir / "base.yaml").exists():
         with (self.config_dir / "base.yaml").open("w") as f:
            yaml.safe_dump({
               "prefix"  : "..",
               "admin_id": admin_id,
               "auths"   : {}}
               , f)

      with (self.config_dir / "base.yaml").open("r") as f:
         self.base_config = yaml.safe_load(f)
      self.cached: clc.OrderedDict = clc.OrderedDict()
      self.locks: ty.Dict[str, asyncio.locks.Lock] = clc.defaultdict(asyncio.locks.Lock)

   def _write_config_file(self, config_id: str, data) -> None:
      local_config_path: pl.Path = self.config_dir / f"{config_id}.yaml"
      with local_config_path.open("w") as f:
         yaml.safe_dump(data, f)

   def _load_config_file(self, config_id: str) -> ty.Dict:
      local_config_path: pl.Path = self.config_dir / f"{config_id}.yaml"
      try:
         with local_config_path.open("r") as f:
            local_config = yaml.safe_load(f)
      except FileNotFoundError:
         local_config = {}
      return local_config

   def of(self, identifiable: ConfigCtx) -> ty.Dict[str, ty.Any]:
      identifier = identifiable.config_identifier
      if identifier in self.cached:
         self.cached.move_to_end(identifier, last=False)
         configs = self.cached[identifier]
      else:
         local_config = self._load_config_file(identifier)

         cleaned_dict, changed = merge_config(self.base_config, local_config)
         # combined_dict = {**self.base_config, **local_config}
         #
         # cleaned_dict = {k: combined_dict[k] for k in self.base_config}
         if changed:
            self._write_config_file(identifier, cleaned_dict)

         self.cached[identifier] = cleaned_dict
         if len(self.cached) > CACHED_CONFIGS:
            self.cached.popitem()

         configs = cleaned_dict

      return configs

   @contextlib.asynccontextmanager
   async def writeable_conf(self, identifiable: ConfigCtx):
      config_id = identifiable.config_identifier
      async with self.locks[config_id]:
         output_dict = self.of(identifiable)
         try:
            yield output_dict
         finally:
            self._write_config_file(config_id, output_dict)
            self.cached[config_id] = output_dict