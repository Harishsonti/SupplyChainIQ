"""Answer Provenance Card — Phase 1 Trust Contract."""
import json
import re
import html as _html
import streamlit as st
from readiness import get_readiness_for_text


# ── Agent Response Parser ────────────────────────────────────────────────────

def parse_agent_response(raw_json):
    """Parse a DATA_AGENT_RUN JSON response into structured provenance fields.

    Returns dict with keys: text, physical_sql, logical_sql, query_id,
    semantic_model_path, result_data, raw_content, status.
    """
    prov = {
        "text": "",
        "physical_sql": None,
        "logical_sql": None,
        "query_id": None,
        "semantic_model_path": None,
        "result_data": None,
        "raw_content": [],
        "status": "unknown",
    }
    try:
        obj = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except (json.JSONDecodeError, TypeError):
        prov["text"] = str(raw_json) if raw_json else ""
        prov["status"] = "parse_error"
        return prov

    if not isinstance(obj, dict):
        prov["text"] = str(obj)
        prov["status"] = "parse_error"
        return prov

    prov["status"] = obj.get("status", "unknown")
    content_blocks = obj.get("content", [])
    prov["raw_content"] = content_blocks

    text_parts = []
    for block in content_blocks:
        btype = block.get("type", "")

        if btype == "text":
            text_parts.append(block.get("text", ""))

        elif btype == "tool_use":
            tu = block.get("tool_use", {})
            inp = tu.get("input", {})
            if tu.get("type") == "system_execute_sql" or tu.get("name") == "system_execute_sql":
                if inp.get("sql"):
                    prov["logical_sql"] = inp["sql"]

        elif btype == "tool_result":
            tr = block.get("tool_result", {})
            tr_type = tr.get("type", "")
            for c in tr.get("content", []):
                j = c.get("json", {})
                if tr_type == "system_execute_sql" or tr.get("name") == "system_execute_sql":
                    if j.get("sql"):
                        prov["physical_sql"] = j["sql"]
                    if j.get("query_id"):
                        prov["query_id"] = j["query_id"]
                    if j.get("semantic_model_path"):
                        prov["semantic_model_path"] = j["semantic_model_path"]
                    if j.get("result_set"):
                        prov["result_data"] = j["result_set"]
                if j.get("semantic_view_fqn") and not prov["semantic_model_path"]:
                    prov["semantic_model_path"] = j["semantic_view_fqn"]

        elif btype == "table":
            tb = block.get("table", {})
            if tb.get("query_id") and not prov["query_id"]:
                prov["query_id"] = tb["query_id"]

    prov["text"] = "\n\n".join(t.strip() for t in text_parts if t.strip())
    return prov


# ── Metric Identification ────────────────────────────────────────────────────

def _normalize_sql(s):
    """Normalize SQL for matching: lowercase, strip quotes/qualifiers, collapse whitespace."""
    if not s:
        return ""
    s = s.lower()
    s = s.replace('"', '')
    # Strip fully-qualified references: db.schema.table.col → col
    s = re.sub(r'\b\w+\.\w+\.\w+\.(\w+)\b', r'\1', s)
    # Strip schema.table.col → col
    s = re.sub(r'\b\w+\.\w+\.(\w+)\b', r'\1', s)
    # Strip table.col → col (but only for known table patterns)
    for tbl in ('order_item_fact', 'scms_shipment_fact', 'customer_dim',
                'product_dim', 'supplier_dim', 'manufacturing_site_dim',
                'geography_dim', 'calendar_dim'):
        s = re.sub(r'\b' + tbl + r'\.(\w+)', r'\1', s)
    # Strip alias.col patterns like t1.col
    s = re.sub(r'\b[a-z]\d*\.(\w+)', r'\1', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# Column signatures for each governed metric — the distinctive columns that
# uniquely identify each metric when found together with the right aggregate.
_METRIC_SIGNATURES = {
    "OTD_PCT": {
        "columns": {"delivery_status"},
        "indicators": {"advance shipping", "shipping on time"},
        "aggregate": "count",
    },
    "DELAY_RATE_PCT": {
        "columns": {"delivery_status"},
        "indicators": {"late delivery"},
        "aggregate": "count",
    },
    "AVG_DELAY_DAYS": {
        "columns": {"days_for_shipping_real", "days_for_shipment_scheduled"},
        "indicators": set(),
        "aggregate": "avg",
    },
    "TOTAL_SALES": {
        "columns": {"sales"},
        "indicators": set(),
        "aggregate": "sum",
    },
    "TOTAL_PROFIT": {
        "columns": {"order_profit_per_order"},
        "indicators": set(),
        "aggregate": "sum",
    },
    "PROFIT_MARGIN_PCT": {
        "columns": {"order_profit_per_order", "sales"},
        "indicators": set(),
        "aggregate": "sum",
    },
    "TOTAL_FREIGHT": {
        "columns": {"freight_cost_usd"},
        "indicators": set(),
        "aggregate": "sum",
    },
    "LOGISTICS_RATE_PCT": {
        "columns": {"freight_cost_usd", "line_item_value"},
        "indicators": set(),
        "aggregate": "sum",
    },
}


@st.cache_data(ttl=600)
def _load_metric_registry(_session):
    """Load METRIC_REGISTRY into a list of dicts. Cached 10 min."""
    rows = _session.sql(
        "SELECT METRIC_ID, METRIC_NAME, VERSION, SOURCE_SYSTEM, GRAIN, "
        "STATUS, DEFINITION, SQL_EXPRESSION "
        "FROM SUPPLYCHAINIQ_COCO.SEMANTIC.METRIC_REGISTRY"
    ).collect()
    return [dict(r.as_dict() if hasattr(r, "as_dict") else zip(
        ["METRIC_ID", "METRIC_NAME", "VERSION", "SOURCE_SYSTEM", "GRAIN",
         "STATUS", "DEFINITION", "SQL_EXPRESSION"], r
    )) for r in rows]


@st.cache_data(ttl=600)
def _load_relationship_governance(_session):
    """Load RELATIONSHIP_GOVERNANCE into a list of dicts. Cached 10 min."""
    rows = _session.sql(
        "SELECT SUBJECT_ENTITY, RELATIONSHIP, OBJECT_ENTITY, LEFT_KEY, "
        "RIGHT_KEY, STATUS, EVIDENCE, NOTES "
        "FROM SUPPLYCHAINIQ_COCO.ONTOLOGY.RELATIONSHIP_GOVERNANCE"
    ).collect()
    return [dict(r.as_dict() if hasattr(r, "as_dict") else zip(
        ["SUBJECT_ENTITY", "RELATIONSHIP", "OBJECT_ENTITY", "LEFT_KEY",
         "RIGHT_KEY", "STATUS", "EVIDENCE", "NOTES"], r
    )) for r in rows]


@st.cache_data(ttl=600)
def _load_data_quality(_session):
    """Load DATA_QUALITY_SCORECARD. Cached 10 min."""
    rows = _session.sql(
        "SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.DATA_QUALITY_SCORECARD"
    ).collect()
    result = {}
    for r in rows:
        d = dict(r.as_dict() if hasattr(r, "as_dict") else {})
        src = d.get("SOURCE_SYSTEM", "")
        result[src] = d
    return result


_NON_COMPUTABLE_KEYWORDS = [
    "fill rate", "days of inventory", "inventory turnover",
    "return rate", "not computable", "not available", "cannot compute",
    "cannot be computed", "not supported", "don't have",
    "do not have the data", "cannot calculate",
]


def identify_metrics(prov, session):
    """Match provenance SQL against METRIC_REGISTRY.

    Resolution order:
    1. SQL expression fragment match (handles quotes/qualifiers)
    2. Column+aggregate signature match
    3. Metric name/ID in answer text (fallback)

    Returns list of dicts with metric info + resolution_method.
    """
    registry = _load_metric_registry(session)
    raw_sql = prov.get("physical_sql") or prov.get("logical_sql") or ""
    sql_norm = _normalize_sql(raw_sql)
    answer_text = (prov.get("text") or "").lower()

    # Check for non-computable / refusal
    if any(kw in answer_text for kw in _NON_COMPUTABLE_KEYWORDS):
        return [{
            "METRIC_ID": "NOT_COMPUTABLE",
            "METRIC_NAME": "Non-Computable Metric",
            "VERSION": None,
            "SOURCE_SYSTEM": None,
            "GRAIN": None,
            "STATUS": "Not Computable",
            "DEFINITION": "Requested metric cannot be computed from available data.",
            "SQL_EXPRESSION": None,
            "resolution_method": "REFUSAL_DETECTED",
        }]

    if not sql_norm:
        return [{
            "METRIC_ID": "UNRESOLVED",
            "METRIC_NAME": "Unknown",
            "VERSION": None,
            "SOURCE_SYSTEM": None,
            "GRAIN": None,
            "STATUS": "Unknown",
            "DEFINITION": "No SQL available to match against metric registry.",
            "SQL_EXPRESSION": None,
            "resolution_method": "UNRESOLVED",
        }]

    matched = []

    # Strategy 1: SQL expression match (normalized — strips quotes/qualifiers)
    for m in registry:
        expr_norm = _normalize_sql(m.get("SQL_EXPRESSION", ""))
        if not expr_norm:
            continue
        # Extract aggregate fragments robustly (handle nested parens)
        frags = _extract_aggregate_fragments(expr_norm)
        if frags and all(_fragment_in_sql(f, sql_norm) for f in frags):
            matched.append({**m, "resolution_method": "SQL_EXPRESSION_MATCH"})
            continue
        # Full expression containment
        if expr_norm in sql_norm:
            matched.append({**m, "resolution_method": "SQL_EXPRESSION_MATCH"})

    # Strategy 2: Column+aggregate signature match
    if not matched:
        for m in registry:
            mid = m.get("METRIC_ID", "")
            sig = _METRIC_SIGNATURES.get(mid)
            if not sig:
                continue
            cols = sig["columns"]
            indicators = sig["indicators"]
            agg = sig["aggregate"]
            # All distinctive columns must appear in the SQL
            if not all(re.search(r'\b' + re.escape(c) + r'\b', sql_norm) for c in cols):
                continue
            # The aggregate function must appear
            if agg not in sql_norm:
                continue
            # All indicator strings must appear (e.g., 'advance shipping')
            if indicators and not all(ind in sql_norm for ind in indicators):
                continue
            matched.append({**m, "resolution_method": "COLUMN_SIGNATURE_MATCH"})

    # Strategy 3: Metric name in answer text (last resort)
    if not matched:
        for m in registry:
            mname = (m.get("METRIC_NAME") or "").lower()
            mid = (m.get("METRIC_ID") or "").lower().replace("_", " ")
            if mname and (mname in answer_text or mid in answer_text):
                matched.append({**m, "resolution_method": "ANSWER_TEXT_FALLBACK"})

    if not matched:
        return [{
            "METRIC_ID": "UNRESOLVED",
            "METRIC_NAME": "Unresolved Metric",
            "VERSION": None,
            "SOURCE_SYSTEM": None,
            "GRAIN": None,
            "STATUS": "Unknown",
            "DEFINITION": "Could not match generated SQL to any registered metric.",
            "SQL_EXPRESSION": None,
            "resolution_method": "UNRESOLVED",
        }]

    return matched


def _extract_aggregate_fragments(expr):
    """Extract aggregate function calls from a SQL expression, handling nested parens."""
    frags = []
    for agg in ('count_if', 'count', 'sum', 'avg', 'min', 'max'):
        for m in re.finditer(agg + r'\s*\(', expr):
            start = m.start()
            depth = 0
            end = start
            for i in range(m.end() - 1, len(expr)):
                if expr[i] == '(':
                    depth += 1
                elif expr[i] == ')':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end > start:
                frags.append(expr[start:end])
    return frags


def _fragment_in_sql(fragment, sql):
    """Check if an aggregate fragment's semantic content appears in the SQL.
    Handles COUNT(CASE WHEN ... THEN 1 END) as equivalent to COUNT_IF(...)."""
    if fragment in sql:
        return True
    # Extract the inner condition from count_if(condition)
    m = re.match(r'count_if\s*\((.+)\)$', fragment, re.DOTALL)
    if m:
        condition = m.group(1).strip()
        # Check for count(case when <condition> then 1 end) pattern
        case_pattern = r'count\s*\(\s*case\s+when\s+' + re.escape(condition)
        if re.search(case_pattern, sql):
            return True
        # Also check if the condition itself appears near a count
        if condition in sql and 'count' in sql:
            return True
    # For sum/avg — check if the column inside appears with the function
    m2 = re.match(r'(sum|avg)\s*\((.+)\)$', fragment, re.DOTALL)
    if m2:
        func, inner = m2.group(1), m2.group(2).strip()
        if func in sql and inner in sql:
            return True
    return False


# ── Governance Identification ────────────────────────────────────────────────

_TABLE_PATTERNS = {
    "ORDER_ITEM_FACT": re.compile(r"order_item_fact", re.IGNORECASE),
    "SCMS_SHIPMENT_FACT": re.compile(r"scms_shipment_fact", re.IGNORECASE),
    "CUSTOMER_DIM": re.compile(r"customer_dim", re.IGNORECASE),
    "PRODUCT_DIM": re.compile(r"product_dim", re.IGNORECASE),
    "SUPPLIER_DIM": re.compile(r"supplier_dim", re.IGNORECASE),
    "MANUFACTURING_SITE_DIM": re.compile(r"manufacturing_site_dim", re.IGNORECASE),
    "GEOGRAPHY_DIM": re.compile(r"geography_dim", re.IGNORECASE),
    "CALENDAR_DIM": re.compile(r"calendar_dim", re.IGNORECASE),
}


def identify_governance(prov, session):
    """Identify applicable governance rules from the SQL tables used.

    Returns dict with tables_used, applicable_rules, cross_source_detected.
    """
    sql = prov.get("physical_sql") or prov.get("logical_sql") or ""
    gov_rules = _load_relationship_governance(session)

    tables_used = [name for name, pat in _TABLE_PATTERNS.items() if pat.search(sql)]

    has_dataco = any(t in ("ORDER_ITEM_FACT", "CUSTOMER_DIM", "PRODUCT_DIM", "CALENDAR_DIM") for t in tables_used)
    has_scms = any(t in ("SCMS_SHIPMENT_FACT", "SUPPLIER_DIM", "MANUFACTURING_SITE_DIM") for t in tables_used)
    cross_source = has_dataco and has_scms

    applicable = []
    for rule in gov_rules:
        subj = rule.get("SUBJECT_ENTITY", "")
        obj_ = rule.get("OBJECT_ENTITY", "")
        # Map entity names to table patterns
        entity_tables = {
            "CUSTOMER": "CUSTOMER_DIM", "PRODUCT": "PRODUCT_DIM",
            "ORDER": "ORDER_ITEM_FACT", "ORDER_ITEM": "ORDER_ITEM_FACT",
            "SUPPLIER": "SUPPLIER_DIM", "MANUFACTURING_SITE": "MANUFACTURING_SITE_DIM",
            "SHIPMENT": "SCMS_SHIPMENT_FACT", "LOGISTICS": "SCMS_SHIPMENT_FACT",
            "GEOGRAPHY": "GEOGRAPHY_DIM",
        }
        subj_table = entity_tables.get(subj)
        obj_table = entity_tables.get(obj_)
        if subj_table in tables_used and obj_table in tables_used:
            applicable.append(rule)

    return {
        "tables_used": tables_used,
        "applicable_rules": applicable,
        "cross_source_detected": cross_source,
    }


# ── Data Quality Notes ───────────────────────────────────────────────────────

def get_data_quality_notes(metrics, governance, session):
    """Build data quality notes from existing scorecard data."""
    dq = _load_data_quality(session)
    notes = []
    sources = set()
    for m in metrics:
        src = m.get("SOURCE_SYSTEM")
        if src:
            sources.add(src)

    for t in governance.get("tables_used", []):
        if t in ("SCMS_SHIPMENT_FACT", "SUPPLIER_DIM", "MANUFACTURING_SITE_DIM"):
            sources.add("SCMS")
        elif t in ("ORDER_ITEM_FACT", "CUSTOMER_DIM", "PRODUCT_DIM", "CALENDAR_DIM"):
            sources.add("DataCo")

    scms_dq = dq.get("SCMS", {})
    if "SCMS" in sources and scms_dq:
        nf = scms_dq.get("NULL_FREIGHT_PCT")
        nw = scms_dq.get("NULL_WEIGHT_PCT")
        if nf is not None:
            notes.append(f"SCMS: {nf}% of freight costs are NULL")
        if nw is not None:
            notes.append(f"SCMS: {nw}% of weights are NULL")

    dataco_dq = dq.get("DataCo", {})
    if "DataCo" in sources and dataco_dq:
        ns = dataco_dq.get("NULL_SALES_PCT")
        if ns is not None and float(ns) > 0:
            notes.append(f"DataCo: {ns}% of sales are NULL")

    if not notes:
        notes.append("No metric-specific coverage metadata available.")

    return notes


# ── Build Full Provenance Object ─────────────────────────────────────────────

def build_provenance(prov, session):
    """Build the complete provenance object from parsed agent response."""
    metrics = identify_metrics(prov, session)
    governance = identify_governance(prov, session)
    dq_notes = get_data_quality_notes(metrics, governance, session)

    # Phase 3: attach readiness info for refusals/non-computable mentions
    readiness_matches = []
    text = prov.get("text", "")
    is_refusal = any(m.get("resolution_method") == "REFUSAL_DETECTED" for m in metrics)
    if is_refusal and text:
        readiness_matches = get_readiness_for_text(text, session)

    return {
        "metric_ids": [m["METRIC_ID"] for m in metrics],
        "metric_names": [m["METRIC_NAME"] for m in metrics],
        "definition_version": [m.get("VERSION") for m in metrics],
        "definition": [m.get("DEFINITION") for m in metrics],
        "source_system": list({m.get("SOURCE_SYSTEM") for m in metrics if m.get("SOURCE_SYSTEM")}),
        "grain": list({m.get("GRAIN") for m in metrics if m.get("GRAIN")}),
        "semantic_view": prov.get("semantic_model_path"),
        "physical_sql": prov.get("physical_sql"),
        "logical_sql": prov.get("logical_sql"),
        "query_id": prov.get("query_id"),
        "governance_status": [r.get("STATUS") for r in governance.get("applicable_rules", [])],
        "governance_evidence": [r.get("EVIDENCE") for r in governance.get("applicable_rules", [])],
        "data_quality_notes": dq_notes,
        "provenance_resolution_method": list({m.get("resolution_method") for m in metrics}),
        "tables_used": governance.get("tables_used", []),
        "cross_source_detected": governance.get("cross_source_detected", False),
        "applicable_rules": governance.get("applicable_rules", []),
        "metrics_detail": metrics,
        "readiness_matches": readiness_matches,
    }


# ── Render Provenance Card ───────────────────────────────────────────────────

def render_provenance_card(provenance):
    """Render the Answer Provenance Card in Streamlit."""
    metrics = provenance.get("metrics_detail", [])
    is_refusal = any(m.get("resolution_method") == "REFUSAL_DETECTED" for m in metrics)
    is_unresolved = all(m.get("resolution_method") == "UNRESOLVED" for m in metrics)
    resolution = provenance.get("provenance_resolution_method", [])
    res_label = ", ".join(sorted(resolution)) if resolution else "UNKNOWN"

    if is_refusal:
        severity = "warning"
        status_label = "Governed Refusal / Not Computable"
    elif is_unresolved:
        severity = "info"
        status_label = "Unresolved"
    else:
        severity = "success"
        status_label = "Governed"

    color_map = {
        "success": "#2e7d32",
        "warning": "#e65100",
        "info": "#1565c0",
    }
    border_color = color_map.get(severity, "#666")

    # Build card HTML
    card_parts = []

    # Metric row
    for m in metrics:
        mid = m.get("METRIC_ID", "")
        mname = m.get("METRIC_NAME", "Unknown")
        ver = m.get("VERSION") or "—"
        src = m.get("SOURCE_SYSTEM") or "—"
        grain = m.get("GRAIN") or "—"
        defn = m.get("DEFINITION") or "—"
        mstatus = m.get("STATUS") or "—"
        card_parts.append(
            f'<div style="margin-bottom:6px;">'
            f'<strong>{_html.escape(mname)}</strong>'
            f' <span style="opacity:0.6;font-size:0.78rem;">({_html.escape(mid)} · v{_html.escape(str(ver))})</span>'
            f'<br/><span style="font-size:0.82rem;">Source: {_html.escape(src)} · '
            f'Grain: {_html.escape(grain)} · Status: {_html.escape(mstatus)}</span>'
            f'<br/><span style="font-size:0.78rem;opacity:0.7;">{_html.escape(defn)}</span>'
            f'</div>'
        )

    # Semantic view
    sv = provenance.get("semantic_view") or "—"
    card_parts.append(
        f'<div style="font-size:0.82rem;margin-top:4px;">'
        f'<strong>Semantic model:</strong> {_html.escape(sv)}'
        f'</div>'
    )

    # Governance
    rules = provenance.get("applicable_rules", [])
    if rules:
        gov_items = []
        for r in rules:
            gov_items.append(
                f'{r.get("SUBJECT_ENTITY","?")}→{r.get("OBJECT_ENTITY","?")}: '
                f'{r.get("STATUS","?")} ({r.get("EVIDENCE","")})'
            )
        card_parts.append(
            f'<div style="font-size:0.82rem;margin-top:4px;">'
            f'<strong>Governance:</strong> '
            + " · ".join(_html.escape(g) for g in gov_items)
            + '</div>'
        )
    elif provenance.get("cross_source_detected"):
        card_parts.append(
            '<div style="font-size:0.82rem;margin-top:4px;color:#e65100;">'
            '<strong>⚠ Cross-source query detected</strong> — no governed join path found'
            '</div>'
        )

    # Data quality
    dq = provenance.get("data_quality_notes", [])
    if dq:
        card_parts.append(
            f'<div style="font-size:0.78rem;margin-top:4px;opacity:0.7;">'
            f'<strong>Data quality:</strong> '
            + " · ".join(_html.escape(n) for n in dq)
            + '</div>'
        )

    # Phase 3: Readiness info for refusals
    readiness = provenance.get("readiness_matches", [])
    if readiness:
        for rm in readiness:
            card_parts.append(
                f'<div style="font-size:0.82rem;margin-top:6px;padding:8px 10px;'
                f'background:rgba(232,174,85,0.1);border-radius:4px;border:1px solid rgba(232,174,85,0.3);">'
                f'<strong>Data Readiness — {_html.escape(rm.get("METRIC_NAME",""))}</strong>'
                f'<br/><span style="font-size:0.78rem;">Status: <strong>Not Computable</strong></span>'
                f'<br/><span style="font-size:0.78rem;">Required: {_html.escape(rm.get("REQUIRED_INPUTS",""))}</span>'
                f'<br/><span style="font-size:0.78rem;color:#e8ae55;">Blocked: {_html.escape(rm.get("BLOCKING_REASON",""))}</span>'
                f'<br/><span style="font-size:0.78rem;color:#6b9e8a;">Unlock: {_html.escape(rm.get("WHAT_DATA_WOULD_UNLOCK",""))}</span>'
                f'</div>'
            )

    # Resolution method
    card_parts.append(
        f'<div style="font-size:0.75rem;margin-top:6px;opacity:0.5;">'
        f'Resolution: {_html.escape(res_label)}'
        f'</div>'
    )

    card_html = (
        f'<div style="border-left:3px solid {border_color};padding:10px 14px;'
        f'margin:10px 0;background:rgba(0,0,0,0.02);border-radius:4px;">'
        f'<div style="font-size:0.75rem;font-weight:600;text-transform:uppercase;'
        f'letter-spacing:0.05em;color:{border_color};margin-bottom:6px;">'
        f'{_html.escape(status_label)}</div>'
        + "\n".join(card_parts)
        + '</div>'
    )

    st.markdown(card_html, unsafe_allow_html=True)

    # Technical provenance expander
    with st.expander("Technical provenance"):
        qid = provenance.get("query_id")
        if qid:
            st.markdown(f"**Query ID:** `{qid}`")

        psql = provenance.get("physical_sql")
        if psql:
            st.markdown("**SQL used:**")
            st.code(psql, language="sql")
        else:
            st.markdown("*No SQL captured for this response.*")

        st.markdown(f"**Semantic model:** `{sv}`")
        tables = provenance.get("tables_used", [])
        if tables:
            st.markdown(f"**Tables:** {', '.join(tables)}")
