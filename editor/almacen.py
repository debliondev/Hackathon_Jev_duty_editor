"""Persistencia en SQLite: piezas, decisiones, cola de revisión y feedback humano.

El feedback del editor (cuando resuelve una pieza de la cola) es una ETIQUETA NUEVA: sirve para
recalibrar umbrales y para la revisión semanal de desacuerdos JEV vs. humano.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from editor.config import RAIZ
from editor.modelos import Decision, Pieza

RUTA_DB_DEFECTO = Path(os.getenv("EDITOR_DB", RAIZ / "data" / "editor.db"))

ESQUEMA = """
CREATE TABLE IF NOT EXISTS piezas (
    pieza_id TEXT PRIMARY KEY, canal TEXT, formato TEXT, texto TEXT, metadatos TEXT
);
CREATE TABLE IF NOT EXISTS decisiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pieza_id TEXT, veredicto TEXT, calidad REAL,
    costo_usd REAL, decision TEXT, creado_el TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pieza_id TEXT, veredicto_ia TEXT,
    veredicto_humano TEXT, nota TEXT, creado_el TEXT
);
"""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Almacen:
    def __init__(self, ruta: Path | str = RUTA_DB_DEFECTO) -> None:
        self.ruta = str(ruta)
        if self.ruta != ":memory:":
            Path(self.ruta).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.ruta, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.executescript(ESQUEMA)

    def guardar(self, pieza: Pieza, decision: Decision) -> None:
        with self._con:
            self._con.execute(
                "INSERT OR REPLACE INTO piezas VALUES (?, ?, ?, ?, ?)",
                (
                    pieza.id,
                    pieza.canal_destino,
                    pieza.formato,
                    pieza.texto,
                    json.dumps(pieza.metadatos),
                ),
            )
            self._con.execute(
                "INSERT INTO decisiones (pieza_id, veredicto, calidad, costo_usd, decision, creado_el)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    decision.pieza_id,
                    decision.veredicto,
                    decision.calidad,
                    decision.costo_usd,
                    json.dumps(decision.a_dict(), ensure_ascii=False),
                    _ahora(),
                ),
            )

    def _ultimas_decisiones(self) -> list[sqlite3.Row]:
        return self._con.execute(
            "SELECT d.*, p.texto, p.canal FROM decisiones d JOIN piezas p USING (pieza_id)"
            " WHERE d.id IN (SELECT MAX(id) FROM decisiones GROUP BY pieza_id)"
        ).fetchall()

    def cola(self) -> list[dict[str, Any]]:
        """Piezas cuya última decisión es REVISAR y que ningún humano ha resuelto aún."""
        resueltas = {r["pieza_id"] for r in self._con.execute("SELECT pieza_id FROM feedback")}
        return [
            {"pieza_id": r["pieza_id"], "canal": r["canal"], "texto": r["texto"],
             "decision": Decision.desde_dict(json.loads(r["decision"]))}
            for r in self._ultimas_decisiones()
            if r["veredicto"] == "revisar" and r["pieza_id"] not in resueltas
        ]  # fmt: skip

    def resolver(self, pieza_id: str, veredicto_humano: str, nota: str = "") -> None:
        fila = self._con.execute(
            "SELECT veredicto FROM decisiones WHERE pieza_id = ? ORDER BY id DESC LIMIT 1",
            (pieza_id,),
        ).fetchone()
        if fila is None:
            raise KeyError(pieza_id)
        with self._con:
            self._con.execute(
                "INSERT INTO feedback (pieza_id, veredicto_ia, veredicto_humano, nota, creado_el)"
                " VALUES (?, ?, ?, ?, ?)",
                (pieza_id, fila["veredicto"], veredicto_humano, nota, _ahora()),
            )

    def feedback(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._con.execute("SELECT * FROM feedback ORDER BY id")]

    def metricas(self) -> dict[str, Any]:
        filas = self._ultimas_decisiones()
        n = len(filas)
        conteo = Counter(r["veredicto"] for r in filas)
        motivos: Counter[str] = Counter()
        for r in filas:
            for m in json.loads(r["decision"])["motivos"]:
                motivos[m["codigo"].split(":")[0]] += 1
        costo = self._con.execute("SELECT COALESCE(SUM(costo_usd), 0) FROM decisiones").fetchone()[
            0
        ]
        return {
            "piezas": n,
            "distribucion": dict(conteo),
            "automatizacion": (n - conteo.get("revisar", 0)) / n if n else None,
            "motivos": dict(motivos.most_common()),
            "costo_acumulado_usd": costo,
            "en_cola": len(self.cola()),
            "resueltas_por_humano": len(self.feedback()),
        }
