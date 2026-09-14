import csv
import json
import textwrap
from pathlib import Path
from typing import Any, Dict, Iterable, List


def classify_cif_neighbourhood(exportable_count: int, min_fit_ready: int = 3) -> str:
    if exportable_count <= 0:
        return "blocked"
    if exportable_count < min_fit_ready:
        return "sparse"
    return "fit_ready"


def render_crystaldb_neighbourhood_pdf(
    retrieval_result: dict,
    output_pdf: Path,
    output_json: Path | None = None,
    output_csv: Path | None = None,
    title: str = "Crystal-DB retrieval neighbourhood",
) -> dict:
    neighbours = _normalise_neighbours(retrieval_result.get("neighbours", []))
    exportable_count = sum(1 for row in neighbours if row["cif_exportable"])
    spp_status = classify_cif_neighbourhood(exportable_count)

    summary = {
        "title": title,
        "query": retrieval_result.get("query", ""),
        "retrieval_mode": retrieval_result.get("retrieval_mode", ""),
        "k": retrieval_result.get("k"),
        "database_label": retrieval_result.get("database_label", ""),
        "fixture_label": retrieval_result.get("fixture_label", ""),
        "intended_csp_use": retrieval_result.get("intended_csp_use", ""),
        "neighbour_count": len(neighbours),
        "exportable_cif_count": exportable_count,
        "spp_corpus_status": spp_status,
        "provenance_note": retrieval_result.get(
            "provenance_note",
            "Deterministic fixture evidence; CIF exportability is recorded separately from retrieval relevance.",
        ),
    }
    audit_payload = dict(retrieval_result)
    audit_payload["computed"] = summary
    audit_payload["neighbours"] = neighbours

    output_pdf = Path(output_pdf)
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    _write_pdf(audit_payload, summary, output_pdf)

    if output_json is not None:
        output_json = Path(output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(audit_payload, indent=2, sort_keys=True), encoding="utf-8")

    if output_csv is not None:
        output_csv = Path(output_csv)
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(neighbours, output_csv)

    return {
        "pdf_path": str(output_pdf),
        "json_path": str(output_json) if output_json is not None else None,
        "csv_path": str(output_csv) if output_csv is not None else None,
        "exportable_cif_count": exportable_count,
        "neighbour_count": len(neighbours),
        "spp_corpus_status": spp_status,
    }


def _normalise_neighbours(neighbours: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for index, item in enumerate(neighbours, start=1):
        cif_exportable = bool(item.get("cif_exportable", False))
        rows.append(
            {
                "rank": item.get("rank", index),
                "structure_id": item.get("structure_id", ""),
                "formula": item.get("formula", ""),
                "similarity": item.get("similarity"),
                "space_group": item.get("space_group", ""),
                "cif_exportable": cif_exportable,
                "cif_path": item.get("cif_path"),
                "blocked_reason": item.get("blocked_reason"),
            }
        )
    return rows


def _write_csv(neighbours: List[Dict[str, Any]], output_csv: Path) -> None:
    fields = [
        "rank",
        "structure_id",
        "formula",
        "similarity",
        "space_group",
        "cif_exportable",
        "cif_path",
        "blocked_reason",
    ]
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(neighbours)


def _write_pdf(audit_payload: Dict[str, Any], summary: Dict[str, Any], output_pdf: Path) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    neighbours = audit_payload["neighbours"]
    with PdfPages(output_pdf) as pdf:
        fig = plt.figure(figsize=(11.69, 8.27))
        fig.patch.set_facecolor("white")

        fig.text(0.04, 0.955, summary["title"], fontsize=17, fontweight="bold", ha="left", va="top")
        fig.text(
            0.04,
            0.915,
            _wrap(f"Query: {summary['query']}", 145),
            fontsize=9.5,
            ha="left",
            va="top",
        )
        fig.text(
            0.04,
            0.875,
            (
                f"Mode: {summary['retrieval_mode']} | k={summary['k']} | "
                f"exportable CIFs: {summary['exportable_cif_count']}/{summary['neighbour_count']} | "
                f"SPP status: {summary['spp_corpus_status']}"
            ),
            fontsize=9.5,
            ha="left",
            va="top",
        )
        fig.add_artist(plt.Line2D([0.04, 0.96], [0.852, 0.852], color="#303030", linewidth=0.8))

        left_ax = fig.add_axes([0.045, 0.155, 0.285, 0.67])
        left_ax.axis("off")
        left_ax.add_patch(
            plt.Rectangle((0, 0), 1, 1, fill=False, edgecolor="#9a9a9a", linewidth=0.9, transform=left_ax.transAxes)
        )
        left_ax.text(0.045, 0.955, "Query context", fontsize=11, fontweight="bold", va="top")
        context_lines = [
            ("Query", summary["query"]),
            ("Intended CSP use", summary["intended_csp_use"] or "not specified"),
            ("Requested top-k", str(summary["k"])),
            ("Neighbours returned", str(summary["neighbour_count"])),
            ("Exportable CIFs", str(summary["exportable_cif_count"])),
            ("SPP corpus status", summary["spp_corpus_status"]),
            ("Database", summary["database_label"] or "not specified"),
            ("Fixture/timestamp", summary["fixture_label"] or audit_payload.get("timestamp", "not recorded")),
        ]
        y = 0.88
        for label, value in context_lines:
            left_ax.text(0.045, y, label, fontsize=8.3, fontweight="bold", va="top")
            y -= 0.035
            left_ax.text(0.045, y, _wrap(str(value), 34), fontsize=8.2, va="top")
            y -= 0.09

        table_ax = fig.add_axes([0.35, 0.155, 0.61, 0.67])
        table_ax.axis("off")
        columns = ["Rank", "Structure ID", "Formula", "Similarity", "Space group", "CIF status", "CIF/path or reason"]
        cell_text = [_table_row(row) for row in neighbours]
        table = table_ax.table(
            cellText=cell_text,
            colLabels=columns,
            cellLoc="left",
            loc="upper left",
            colWidths=[0.06, 0.2, 0.105, 0.095, 0.12, 0.12, 0.3],
            bbox=[0, 0, 1, 1],
        )
        table.auto_set_font_size(False)
        table.set_fontsize(7.2)
        for (row_idx, _col_idx), cell in table.get_celld().items():
            cell.set_edgecolor("#b7b7b7")
            cell.set_linewidth(0.45)
            if row_idx == 0:
                cell.set_facecolor("#e8e8e8")
                cell.set_text_props(weight="bold", color="#111111")
            elif row_idx % 2 == 0:
                cell.set_facecolor("#f7f7f7")

        fig.add_artist(plt.Line2D([0.04, 0.96], [0.105, 0.105], color="#606060", linewidth=0.6))
        fig.text(
            0.04,
            0.082,
            f"Exportable CIF count: {summary['exportable_cif_count']} / {summary['neighbour_count']}",
            fontsize=8.8,
            ha="left",
        )
        fig.text(
            0.36,
            0.082,
            f"SPP corpus status: {summary['spp_corpus_status']}",
            fontsize=8.8,
            ha="left",
        )
        fig.text(0.04, 0.052, _wrap(summary["provenance_note"], 145), fontsize=7.8, ha="left")

        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def _table_row(row: Dict[str, Any]) -> List[str]:
    status = "exportable" if row["cif_exportable"] else "blocked"
    location = row.get("cif_path") if row["cif_exportable"] else row.get("blocked_reason")
    similarity = row.get("similarity")
    if isinstance(similarity, (int, float)):
        similarity_text = f"{similarity:.2f}"
    else:
        similarity_text = "" if similarity is None else str(similarity)
    return [
        str(row.get("rank", "")),
        _wrap(str(row.get("structure_id", "")), 18),
        str(row.get("formula", "")),
        similarity_text,
        str(row.get("space_group", "")),
        status,
        _wrap(_truncate(str(location or ""), 46), 24),
    ]


def _wrap(value: str, width: int) -> str:
    return "\n".join(textwrap.wrap(value, width=width, break_long_words=False)) or ""


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."
