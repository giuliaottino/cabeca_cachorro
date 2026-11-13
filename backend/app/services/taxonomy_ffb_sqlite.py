"""Validação taxonômica contra a Lista Oficial da Flora e Funga do Brasil (SQLite local).

Desenho:
- índice de gêneros e famílias carregado uma vez em memória (~14 mil gêneros);
- espécies consultadas pelo índice ``norm_binomial`` e memorizadas por binômio;
- sugestões por similaridade (difflib) só quando o nome não é encontrado.
"""
from __future__ import annotations

import difflib
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from app.config import settings
from app.schemas.issues import ValidationIssue
from app.services.normalization import norm
from app.services.rule_engine import issue

SOURCE_NAME = "Flora e Funga do Brasil - Lista Oficial"
SOURCE_URL = "https://ipt.jbrj.gov.br/jbrj/archive.do?r=lista_especies_flora_brasil"
ACCEPTED = "NOME_ACEITO"
SYNONYM = "SINONIMO"
SPECIES_RANK = "ESPECIE"
INFRA_RANKS = {"VARIEDADE", "SUB_ESPECIE", "FORMA"}

# Nomes alternativos de família (Código de Nomenclatura, Art. 18.5) -> nome usado pela FFB
ALT_FAMILY_NAMES = {
    "leguminosae": "fabaceae", "compositae": "asteraceae", "guttiferae": "clusiaceae", "palmae": "arecaceae",
    "gramineae": "poaceae", "cruciferae": "brassicaceae", "umbelliferae": "apiaceae", "labiatae": "lamiaceae",
}
_UF_BY_NAME_HINT = "BR-"


@dataclass
class GenusInfo:
    name: str
    accepted: bool = False
    families: Counter = field(default_factory=Counter)      # famílias dos nomes aceitos do gênero
    any_families: Counter = field(default_factory=Counter)  # famílias de qualquer nome do gênero
    accepted_genus: str | None = None                       # quando o gênero é sinônimo


class TaxonomyReference:
    def __init__(self, db_path=None):
        self.db_path = db_path or settings.taxonomy_db
        self._local = threading.local()
        self._lock = threading.Lock()
        self._genera: dict[str, GenusInfo] | None = None
        self._families: dict[str, str] | None = None
        self._genus_keys: list[str] = []
        self._family_keys: list[str] = []
        self._meta: dict[str, Any] = {}

    # -- conexão -------------------------------------------------------------
    def _con(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            uri = f"file:{self.db_path.as_posix()}?mode=ro&immutable=1"
            con = sqlite3.connect(uri, uri=True, check_same_thread=False)
            con.row_factory = sqlite3.Row
            self._local.con = con
        return con

    def available(self) -> bool:
        return self.db_path.exists()

    def load(self) -> None:
        """Carrega índices em memória (idempotente e thread-safe)."""
        if self._genera is not None:
            return
        with self._lock:
            if self._genera is not None:
                return
            con = self._con()
            genera: dict[str, GenusInfo] = {}
            families: dict[str, str] = {}
            rows = con.execute(
                """SELECT norm_genus, genus, family, norm_family, taxon_rank, taxonomic_status, accepted_genus
                   FROM ffb_taxon WHERE norm_genus IS NOT NULL AND norm_genus NOT IN ('', 'na')"""
            )
            for r in rows:
                key = r["norm_genus"]
                info = genera.get(key)
                if info is None:
                    info = genera[key] = GenusInfo(name=r["genus"])
                fam = r["family"]
                if fam and fam.upper() != "NA":
                    info.any_families[fam] += 1
                    if r["taxonomic_status"] == ACCEPTED:
                        info.families[fam] += 1
                    families.setdefault(r["norm_family"] or norm(fam), fam)
                if r["taxon_rank"] == "GENERO":
                    if r["taxonomic_status"] == ACCEPTED:
                        info.accepted = True
                        info.name = r["genus"]
                    elif r["taxonomic_status"] == SYNONYM and r["accepted_genus"]:
                        info.accepted_genus = info.accepted_genus or r["accepted_genus"]
                elif r["taxonomic_status"] == ACCEPTED:
                    info.accepted = True
            for r in con.execute("SELECT family, norm_family FROM ffb_taxon WHERE taxon_rank = 'FAMILIA'"):
                if r["family"]:
                    families.setdefault(r["norm_family"] or norm(r["family"]), r["family"])
            self._meta = {row["key"]: row["value"] for row in con.execute("SELECT key, value FROM reference_metadata")}
            self._families = families
            self._family_keys = list(families)
            self._genus_keys = list(genera)
            self._genera = genera

    # -- consultas -----------------------------------------------------------
    def genus(self, genus_norm: str) -> GenusInfo | None:
        self.load()
        assert self._genera is not None
        return self._genera.get(genus_norm)

    def family_exists(self, family_norm: str) -> bool:
        self.load()
        assert self._families is not None
        return family_norm in self._families

    @lru_cache(maxsize=4096)
    def suggest_genus(self, genus_norm: str, limit: int = 3) -> tuple[str, ...]:
        self.load()
        hits = difflib.get_close_matches(genus_norm, self._genus_keys, n=limit, cutoff=0.8)
        return tuple(self._genera[h].name for h in hits)  # type: ignore[index]

    @lru_cache(maxsize=1024)
    def suggest_family(self, family_norm: str) -> str | None:
        self.load()
        hit = difflib.get_close_matches(family_norm, self._family_keys, n=1, cutoff=0.8)
        return self._families[hit[0]] if hit else None  # type: ignore[index]

    @lru_cache(maxsize=16384)
    def binomial_rows(self, binomial_norm: str) -> tuple[dict[str, Any], ...]:
        rows = self._con().execute(
            """SELECT taxon_id, scientific_name, canonical_name, family, genus, specific_epithet,
                      infraspecific_epithet, taxon_rank, taxonomic_status, accepted_taxon_id,
                      accepted_scientific_name, accepted_canonical_name, accepted_family
               FROM ffb_taxon WHERE norm_binomial = ?""",
            (binomial_norm,),
        ).fetchall()
        return tuple(dict(r) for r in rows)

    @lru_cache(maxsize=4096)
    def epithets(self, genus_norm: str) -> dict[str, str]:
        """epíteto normalizado -> binômio de exibição (aceitos primeiro)."""
        rows = self._con().execute(
            """SELECT specific_epithet, genus, taxonomic_status FROM ffb_taxon
               WHERE norm_genus = ? AND taxon_rank = 'ESPECIE' AND specific_epithet IS NOT NULL
               ORDER BY taxonomic_status = 'NOME_ACEITO' DESC""",
            (genus_norm,),
        ).fetchall()
        out: dict[str, str] = {}
        for r in rows:
            out.setdefault(norm(r["specific_epithet"]), f"{r['genus']} {r['specific_epithet']}")
        return out

    @lru_cache(maxsize=16384)
    def states_for(self, taxon_id: str) -> frozenset[str]:
        rows = self._con().execute(
            "SELECT DISTINCT location_id FROM ffb_distribution WHERE taxon_id = ? AND location_id IS NOT NULL",
            (taxon_id,),
        ).fetchall()
        return frozenset(r[0].replace(_UF_BY_NAME_HINT, "") for r in rows if r[0])

    def status(self) -> dict[str, Any]:
        base = {"mode": "ffb_sqlite", "path": str(self.db_path), "source": SOURCE_NAME, "source_url": SOURCE_URL}
        if not self.available():
            return {**base, "status": "missing"}
        try:
            self.load()
        except Exception as exc:  # pragma: no cover - base corrompida
            return {**base, "status": "error", "error": str(exc)}
        return {
            **base,
            "status": "ready",
            "source_version": self._meta.get("source_version", "unspecified"),
            "created_at_utc": self._meta.get("created_at_utc"),
            "taxon_count": int(self._meta.get("taxon_count", 0) or 0),
            "genus_count": len(self._genus_keys),
            "family_count": len(self._family_keys),
        }


REFERENCE = TaxonomyReference()


def reference_status() -> dict[str, Any]:
    return REFERENCE.status()


# ---------------------------------------------------------------------------
# Validação de um registro
# ---------------------------------------------------------------------------
def _first_token(value: Any) -> str:
    text = str(value or "").strip()
    return text.split()[0] if text else ""


def _choose(rows: tuple[dict[str, Any], ...], sp2_norm: str) -> dict[str, Any] | None:
    if sp2_norm:
        candidates = [r for r in rows if norm(r["infraspecific_epithet"]) == sp2_norm]
    else:
        candidates = [r for r in rows if r["taxon_rank"] == SPECIES_RANK]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["taxonomic_status"] != ACCEPTED, r["taxonomic_status"] is None))
    return candidates[0]


def _binomial(name: str | None) -> str:
    return " ".join(norm(name).split()[:2])


def validate_taxonomy_ffb(record: dict[str, Any], *, uf_sigla: str | None = None) -> list[ValidationIssue]:
    ref = REFERENCE
    row = record.get("_row_number")
    family = str(record.get("family") or "").strip()
    genus = str(record.get("genus") or "").strip()
    sp1 = str(record.get("sp1") or "").strip()
    sp2 = str(record.get("sp2") or "").strip()
    src = SOURCE_NAME
    issues: list[ValidationIssue] = []

    family_norm = norm(family)
    if family:
        lookup = ALT_FAMILY_NAMES.get(family_norm, family_norm)
        if not ref.family_exists(lookup):
            sugg = ref.suggest_family(family_norm)
            issues.append(issue(row, "family", "error", "FAMILY_NOT_FOUND_FFB",
                                "Família não encontrada na Flora e Funga do Brasil.", family, suggestion=sugg, source=src))
        if family != family.strip().capitalize() and family.upper() != family:
            issues.append(issue(row, "family", "info", "FAMILY_CAPITALIZATION",
                                "Família deve iniciar com maiúscula e seguir em minúsculas.", family,
                                suggestion=family.capitalize(), source=src))

    if not genus:
        return issues

    genus_token = _first_token(genus)
    genus_norm = norm(genus_token)
    info = ref.genus(genus_norm)
    if info is None:
        suggestions = ref.suggest_genus(genus_norm)
        issues.append(issue(row, "genus", "error", "GENUS_NOT_FOUND_FFB",
                            "Gênero não encontrado na Flora e Funga do Brasil."
                            + ("" if suggestions else " Confira a grafia ou se o gênero ocorre no Brasil."),
                            genus, suggestion=", ".join(suggestions) or None, source=src))
        return issues

    if genus_token != info.name and norm(genus_token) == norm(info.name):
        issues.append(issue(row, "genus", "info", "GENUS_CAPITALIZATION",
                            "Gênero deve iniciar com maiúscula (e sem acentos).", genus, suggestion=info.name, source=src))
    if len(genus.split()) > 1 and not sp1:
        issues.append(issue(row, "genus", "warning", "GENUS_WITH_EPITHET",
                            "Coluna genus contém mais de uma palavra; separe o epíteto em sp1.", genus, source=src))

    if not info.accepted and info.accepted_genus:
        issues.append(issue(row, "genus", "warning", "GENUS_SYNONYM_FFB",
                            f"Gênero tratado como sinônimo na Flora e Funga; nome aceito: {info.accepted_genus}.",
                            genus, suggestion=info.accepted_genus, source=src))

    expected = info.families or info.any_families
    expected_names = {norm(f) for f in expected}
    if family and expected_names:
        fam_lookup = ALT_FAMILY_NAMES.get(family_norm, family_norm)
        best = expected.most_common(1)[0][0]
        if fam_lookup not in expected_names:
            issues.append(issue(row, "family", "warning", "FAMILY_GENUS_MISMATCH",
                                f"Família não coincide com a do gênero {info.name} na Flora e Funga ({best}).",
                                family, suggestion=best, source=src))
        elif fam_lookup != family_norm:
            issues.append(issue(row, "family", "info", "FAMILY_ALTERNATIVE_NAME",
                                f"{family} é nome alternativo válido; a Flora e Funga usa {best}.",
                                family, suggestion=best, source=src))
    elif not family and expected_names:
        issues.append(issue(row, "family", "warning", "FAMILY_EMPTY",
                            "Família vazia; preencha conforme o gênero.", None,
                            suggestion=expected.most_common(1)[0][0], source=src))

    if not sp1 or norm(sp1) in {"sp", "spp", "indet"} or norm(sp1).startswith("sp "):
        return issues

    epithet_token = _first_token(sp1)
    epithet_norm = norm(epithet_token)
    if epithet_token != epithet_token.lower():
        issues.append(issue(row, "sp1", "info", "EPITHET_CAPITALIZATION", "Epíteto específico deve ser escrito em minúsculas.",
                            sp1, suggestion=epithet_token.lower(), source=src))
    if len(sp1.split()) > 1:
        issues.append(issue(row, "sp1", "info", "SP1_EXTRA_TEXT",
                            "sp1 deve conter somente o epíteto (sem autor, var. ou outro texto).", sp1,
                            suggestion=epithet_token, source=src))

    rows = ref.binomial_rows(f"{genus_norm} {epithet_norm}")
    sp2_norm = norm(_first_token(sp2))
    match = _choose(rows, "")
    if match is None:
        epithets = ref.epithets(genus_norm)
        compact = {k.replace(" ", ""): k for k in epithets}
        spelled = compact.get(epithet_norm.replace(" ", ""))
        if spelled and spelled != epithet_norm:
            issues.append(issue(row, "sp1", "warning", "EPITHET_SPELLING",
                                "Epíteto com grafia diferente da Flora e Funga (hífen ou espaço).", sp1,
                                suggestion=epithets[spelled].split(" ", 1)[1], source=src))
            rows = ref.binomial_rows(f"{genus_norm} {spelled}")
            match = _choose(rows, "")
    if match is None:
        hits = difflib.get_close_matches(epithet_norm, list(epithets), n=3, cutoff=0.75)
        issues.append(issue(row, "sp1", "error", "SPECIES_NOT_FOUND_FFB",
                            f"Espécie {info.name} {epithet_token} não encontrada na Flora e Funga do Brasil.",
                            f"{genus} {sp1}", suggestion=", ".join(epithets[h] for h in hits) or None, source=src))
        return issues

    if match["taxonomic_status"] == SYNONYM:
        accepted = match["accepted_scientific_name"] or match["accepted_canonical_name"]
        if accepted and _binomial(accepted) != f"{genus_norm} {epithet_norm}":
            msg = f"Nome é sinônimo na Flora e Funga; nome aceito: {accepted}."
            if match["accepted_family"] and family and norm(match["accepted_family"]) != ALT_FAMILY_NAMES.get(family_norm, family_norm):
                msg += f" Família do nome aceito: {match['accepted_family']}."
            issues.append(issue(row, "sp1", "warning", "TAXON_SYNONYM_FFB", msg, match["scientific_name"],
                                suggestion=accepted, source=src))

    if sp2_norm:
        infra = _choose(rows, sp2_norm)
        if infra is None:
            issues.append(issue(row, "sp2", "warning", "INFRASPECIFIC_NOT_FOUND_FFB",
                                f"Táxon infraespecífico {info.name} {epithet_token} {sp2} não encontrado na Flora e Funga.",
                                sp2, source=src))
        elif infra["taxonomic_status"] == SYNONYM and infra["accepted_scientific_name"]:
            issues.append(issue(row, "sp2", "warning", "TAXON_SYNONYM_FFB",
                                f"Nome infraespecífico é sinônimo; nome aceito: {infra['accepted_scientific_name']}.",
                                infra["scientific_name"], suggestion=infra["accepted_scientific_name"], source=src))

    accepted_id = match["accepted_taxon_id"] or match["taxon_id"]
    if uf_sigla and accepted_id:
        states = ref.states_for(str(accepted_id))
        if states and uf_sigla not in states:
            issues.append(issue(row, "sp1", "info", "SPECIES_NOT_RECORDED_IN_STATE",
                                f"A Flora e Funga não registra ocorrência desta espécie em {uf_sigla} "
                                f"(registrada em: {', '.join(sorted(states))}). Confira a determinação "
                                "ou documente como novo registro.", f"{genus} {sp1}", source=src))
    return issues
