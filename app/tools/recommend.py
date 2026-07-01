"""LangChain Tool 2: recommend_actuators — Pydantic structured extraction → SQL hard filters → ChromaDB semantic ranking."""

import contextlib
import logging
import sqlite3
from typing import Literal

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.db.chroma import get_chroma_collection
from app.db.sqlite import get_sqlite_conn

logger = logging.getLogger(__name__)


class RecommendationFilters(BaseModel):
    # Closed enums: constraining to real catalog values stops the LLM from injecting
    # noise like application_type="Series 76" (the product name), which silently
    # filtered every recommendation to zero rows.
    torque_nm_min: float | None = Field(None, ge=0)
    voltage: Literal["24V", "110V", "220V"] | None = None
    enclosure_type: Literal["explosionproof", "weatherproof"] | None = None
    application_type: Literal["on/off", "modulating"] | None = None


def _extract_filters(requirements: str) -> RecommendationFilters:
    llm = ChatOpenAI(model=settings.model_name, api_key=settings.openai_api_key, temperature=0)
    structured = llm.with_structured_output(RecommendationFilters)
    return structured.invoke([HumanMessage(content=f"Extract structured actuator filter criteria from: {requirements}")])


def _build_where(filters: RecommendationFilters) -> tuple[str, list]:
    conditions = []
    params = []

    if filters.torque_nm_min is not None:
        conditions.append("torque_nm >= ?")
        params.append(filters.torque_nm_min)
    if filters.voltage:
        conditions.append("voltage = ?")
        params.append(filters.voltage)
    if filters.enclosure_type:
        conditions.append("enclosure_type = ?")
        params.append(filters.enclosure_type)
    if filters.application_type:
        # 'on/off and modulating' units satisfy either single-mode request.
        conditions.append("(application_type = ? OR application_type = 'on/off and modulating')")
        params.append(filters.application_type)

    if not conditions:
        return ("1=1", [])
    return (" AND ".join(conditions), params)


def _format_recommendations(rows: list[sqlite3.Row]) -> str:
    lines = [f"Top {len(rows)} actuator recommendations:"]
    for i, row in enumerate(rows, 1):
        lines.append(
            f"{i}. {row['base_part_number']} — {row['enclosure_type']}, "
            f"{row['voltage']}, {row['torque_nm']} Nm ({row['torque_inlbs']} in-lbs), "
            f"{row['application_type']}"
        )
    return "\n".join(lines)


@tool(parse_docstring=True)
def recommend_actuators(requirements: str) -> str:
    """Recommend Series 76 actuators based on natural language technical requirements.

    Args:
        requirements: Natural language description of needs (e.g., 'explosionproof 300 Nm 220V single phase for hazardous environment').
    """
    filters = _extract_filters(requirements)
    where, params = _build_where(filters)

    with contextlib.closing(get_sqlite_conn(settings.db_path)) as conn:
        # Key by (PN, application_type): a base PN can have an on/off row AND a modulating
        # row with DIFFERENT torque (e.g. 761A00-11300000/A is 80 Nm on/off, 65 Nm
        # modulating). Collapsing to one row per PN would show an arbitrary variant's specs
        # (whichever the query planner returns first). They are distinct recommendable
        # options, so each variant is its own candidate.
        candidates: dict[tuple[str, str], sqlite3.Row] = {}
        for row in conn.execute(f"SELECT * FROM actuators WHERE {where}", params):
            candidates[(row["base_part_number"], row["application_type"])] = row

        if not candidates:
            return "No actuators match those requirements. Try relaxing constraints (e.g., lower torque minimum or broader voltage)."

        pns = list({pn for pn, _ in candidates})  # unique PNs for the Chroma metadata filter
        try:
            collection = get_chroma_collection(settings)
            n_results = min(5, len(candidates), collection.count())
            if n_results == 0:
                raise ValueError("ChromaDB collection is empty")
            results = collection.query(
                query_texts=[requirements],
                n_results=n_results,
                where={"base_part_number": {"$in": pns}},
            )
            # Chroma metadata carries both PN and application_type; rank by (PN, app) so the
            # exact variant Chroma matched is the one whose specs we show.
            seen: set[tuple[str, str]] = set()
            top_rows = []
            for m in results["metadatas"][0]:
                key = (m["base_part_number"], m.get("application_type"))
                if key in candidates and key not in seen:
                    seen.add(key)
                    top_rows.append(candidates[key])
            if top_rows:
                return _format_recommendations(top_rows)
            raise ValueError("no ranked variant matched the candidate set")
        except Exception as e:
            logger.warning("ChromaDB query failed, falling back to SQL results: %s", e)
            return _format_recommendations(list(candidates.values())[:5])
