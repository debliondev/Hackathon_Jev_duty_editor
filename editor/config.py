"""Carga de la configuración (YAML/JSON) y cálculo de sus versiones (hash).

Toda decisión guarda el hash de reglas.yaml y policy.yaml con el que se tomó: así se puede
auditar después qué textos y qué umbrales estaban vigentes.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
DIR_CONFIG = RAIZ / "config"

load_dotenv(RAIZ / ".env")


def hash_archivo(ruta: Path) -> str:
    """Devuelve los primeros 12 caracteres del sha256 del archivo (versión corta y legible)."""
    return hashlib.sha256(ruta.read_bytes()).hexdigest()[:12]


@dataclass(frozen=True)
class Configuracion:
    """Configuración completa del editor, ya parseada."""

    policy: dict[str, Any]
    reglas: dict[str, Any]
    catalogo: dict[str, Any]
    version_policy: str
    version_reglas: str

    @property
    def modelo(self) -> str:
        return self.policy["modelo"]

    def politica_de_canal(self, canal: str) -> dict[str, float]:
        """Umbrales de la política que aplica al canal (p. ej. linkedin → post_organico)."""
        nombre = self.policy["canal_a_politica"][canal]
        return self.policy["politicas"][nombre]

    def con_overrides(self, overrides: dict[str, float]) -> Configuracion:
        """Copia de la configuración con los mismos umbrales forzados en TODAS las políticas.

        Se usa en el barrido de umbrales y en el slider de la UI: no toca los archivos.
        """
        policy = copy.deepcopy(self.policy)
        for umbrales in policy["politicas"].values():
            umbrales.update(overrides)
        return Configuracion(
            policy=policy,
            reglas=self.reglas,
            catalogo=self.catalogo,
            version_policy=f"{self.version_policy}+override",
            version_reglas=self.version_reglas,
        )


def cargar_configuracion(dir_config: Path | None = None) -> Configuracion:
    """Lee policy.yaml, reglas.yaml y catalogo.json del directorio de configuración."""
    d = dir_config or DIR_CONFIG
    ruta_policy, ruta_reglas, ruta_catalogo = (
        d / "policy.yaml",
        d / "reglas.yaml",
        d / "catalogo.json",
    )
    return Configuracion(
        policy=yaml.safe_load(ruta_policy.read_text(encoding="utf-8")),
        reglas=yaml.safe_load(ruta_reglas.read_text(encoding="utf-8")),
        catalogo=json.loads(ruta_catalogo.read_text(encoding="utf-8")),
        version_policy=hash_archivo(ruta_policy),
        version_reglas=hash_archivo(ruta_reglas),
    )
