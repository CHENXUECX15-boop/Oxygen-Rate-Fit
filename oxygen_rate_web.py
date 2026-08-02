from __future__ import annotations

import argparse
import cgi
import csv
import json
import shutil
import sys
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from oxygen_rate_fit import (
    ParsedData,
    build_summary_text,
    choose_rate_line,
    iter_input_files,
    linear_fit,
    parse_pyroscience_txt,
    safe_name,
    save_rate_line_png,
    write_rate_line_csv,
    write_selected_csv,
    write_skip_summary,
)


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "oxygen_rate_web_static"
if not STATIC_ROOT.exists():
    STATIC_ROOT = ROOT
UPLOAD_ROOT = ROOT / "oxygen_rate_web_uploads"


DEFAULT_FIT_OPTIONS = {
    "target_r2": 0.9999,
    "min_r2": 0.999,
    "start_after_turn_points": 6,
    "start_window_points": 3,
    "min_start_after_turn_points": None,
    "max_start_after_turn_points": None,
    "min_fit_points": 5,
    "max_fit_points": 20,
    "min_rate_umol_l_s": 1.0,
    "oxygen_floor": 45.0,
    "min_descent_ratio": 0.8,
    "max_half_slope_diff": 0.3,
    "min_start_after_peak_points": 2,
    "max_start_after_peak_points": 6,
    "drop_threshold_umol_l": 2.0,
    "drop_confirm_points": 5,
    "peak_lookback_points": 5,
    "min_edge_rate_fraction": 0.45,
    "edge_rate_points": 2,
    "min_first_rate_fraction": 0.7,
}


def rows_for_json(rows: list[tuple[float, float]]) -> list[list[float]]:
    return [[float(time_s), float(oxygen)] for time_s, oxygen in rows]


def output_dir_for(input_file: Path) -> Path:
    return input_file.parent / "oxygen_rate_fit_web" / safe_name(input_file.stem)


def fit_point_indices(
    rows: list[tuple[float, float]], fit_points: list[tuple[float, float]]
) -> list[int]:
    indices: list[int] = []
    search_start = 0
    for point in fit_points:
        found_index = None
        for index in range(search_start, len(rows)):
            if rows[index] == point:
                found_index = index
                search_start = index + 1
                break
        if found_index is None:
            found_index = rows.index(point)
        indices.append(found_index)
    return indices


def fit_indices(
    rows: list[tuple[float, float]], fit_points: list[tuple[float, float]]
) -> tuple[int, int]:
    indices = fit_point_indices(rows, fit_points)
    return min(indices), max(indices)


def save_fit_outputs(
    input_file: Path,
    parsed: ParsedData,
    fit_points: list[tuple[float, float]],
    note: str,
    axis_limits: dict | None = None,
    output_to_downloads: bool = False,
) -> dict[str, str | bool]:
    fit = linear_fit(fit_points)
    sample_dir = output_dir_for(input_file)
    sample_dir.mkdir(parents=True, exist_ok=True)
    write_selected_csv(sample_dir / "selected_oxygen_data.csv", parsed.rows)
    write_rate_line_csv(sample_dir / "rate_line_points.csv", parsed.rows, fit_points, fit)
    plot_written, plot_path = save_rate_line_png(
        input_file,
        sample_dir,
        parsed.rows,
        fit_points,
        fit,
        axis_limits,
        output_to_downloads=output_to_downloads,
    )
    summary_text = build_summary_text(input_file, parsed, fit, note)
    (sample_dir / "rate_line_summary.txt").write_text(
        summary_text, encoding="utf-8-sig"
    )
    return {
        "fit_start_s": f"{fit.start_s:.3f}",
        "fit_end_s": f"{fit.end_s:.3f}",
        "fit_points": str(fit.n),
        "slope_umol_L_s": f"{fit.slope:.4f}",
        "oxygen_rate_umol_L_s": f"{(-fit.slope):.4f}",
        "intercept_umol_L": f"{fit.intercept:.4f}",
        "r2": f"{fit.r2:.4f}",
        "plot_written": bool(plot_written),
        "plot_path": str(plot_path),
        "output_dir": str(sample_dir),
    }


def sample_payload(
    input_file: Path,
    parsed: ParsedData,
    status: str,
    error: str = "",
    extra: dict | None = None,
    fit_points: list[tuple[float, float]] | None = None,
) -> dict:
    payload = {
        "sample": input_file.parent.name if input_file.parent.name else input_file.stem,
        "name": input_file.name,
        "input_file": str(input_file),
        "rows": rows_for_json(parsed.rows),
        "status": status,
        "error": error,
        "fit_start_index": None,
        "fit_end_index": None,
        "fit_selected_indices": [],
        "fit_start_s": "",
        "fit_end_s": "",
        "fit_points": "",
        "slope_umol_L_s": "",
        "oxygen_rate_umol_L_s": "",
        "intercept_umol_L": "",
        "r2": "",
        "plot_written": False,
        "plot_path": "",
        "output_dir": "",
        "note": "",
    }
    if fit_points:
        selected_indices = fit_point_indices(parsed.rows, fit_points)
        start_index, end_index = min(selected_indices), max(selected_indices)
        payload["fit_start_index"] = start_index
        payload["fit_end_index"] = end_index
        payload["fit_selected_indices"] = selected_indices
    if extra:
        payload.update(extra)
    return payload


def process_file(input_file: Path) -> dict:
    parsed = parse_pyroscience_txt(input_file)
    try:
        fit_points, note = choose_rate_line(parsed.rows, **DEFAULT_FIT_OPTIONS)
    except Exception as exc:
        sample_dir = output_dir_for(input_file)
        write_skip_summary(sample_dir, input_file, str(exc))
        return sample_payload(
            input_file,
            parsed,
            status="skipped",
            error=str(exc),
            extra={
                "output_dir": str(sample_dir),
                "note": "skipped: no candidate matched the fitting rules",
            },
        )

    extra = save_fit_outputs(input_file, parsed, fit_points, note)
    extra["note"] = note
    return sample_payload(
        input_file, parsed, status="ok", extra=extra, fit_points=fit_points
    )


def process_path(path: Path) -> dict:
    files = iter_input_files(path)
    samples = []
    for file_path in files:
        try:
            samples.append(process_file(file_path))
        except Exception as exc:
            samples.append(
                {
                    "sample": file_path.parent.name,
                    "name": file_path.name,
                    "input_file": str(file_path),
                    "rows": [],
                    "status": "error",
                    "error": str(exc),
                }
            )
    write_batch_summary(samples, path)
    return result_payload(samples)


def result_payload(samples: list[dict]) -> dict:
    ok_count = sum(1 for sample in samples if sample.get("status") == "ok")
    return {
        "samples": samples,
        "ok_count": ok_count,
        "total_count": len(samples),
    }


def write_batch_summary(samples: list[dict], input_path: Path) -> None:
    root = input_path if input_path.is_dir() else input_path.parent
    summary_dir = root / "oxygen_rate_fit_web"
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / "batch_summary.csv"
    fieldnames = [
        "sample",
        "input_file",
        "fit_start_s",
        "fit_end_s",
        "fit_points",
        "slope_umol_L_s",
        "oxygen_rate_umol_L_s",
        "intercept_umol_L",
        "r2",
        "plot_written",
        "plot_path",
        "output_dir",
        "note",
        "status",
        "error",
    ]
    with summary_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for sample in samples:
            writer.writerow({field: sample.get(field, "") for field in fieldnames})


def clean_selected_indices(raw_indices: list, row_count: int) -> list[int]:
    indices = sorted(
        {
            int(value)
            for value in raw_indices
            if str(value).strip() != ""
        }
    )
    indices = [index for index in indices if 0 <= index < row_count]
    if len(indices) <= 1:
        return indices
    return list(range(indices[0], indices[-1] + 1))


def refit_file(
    file_path: Path,
    start_index: int | None = None,
    end_index: int | None = None,
    selected_indices: list | None = None,
    axis_limits: dict | None = None,
    output_to_downloads: bool = False,
) -> dict:
    parsed = parse_pyroscience_txt(file_path)
    if selected_indices is not None:
        indices = clean_selected_indices(selected_indices, len(parsed.rows))
        fit_points = [parsed.rows[index] for index in indices]
        note = (
            "manual rate_line: selected rows "
            f"{','.join(str(index) for index in indices)}; saved from web UI"
        )
    else:
        if start_index is None or end_index is None:
            raise ValueError("Manual fit needs selected indices or start/end indices.")
        if start_index > end_index:
            start_index, end_index = end_index, start_index
        start_index = max(0, min(len(parsed.rows) - 1, start_index))
        end_index = max(0, min(len(parsed.rows) - 1, end_index))
        fit_points = parsed.rows[start_index : end_index + 1]
        note = (
            f"manual rate_line: selected rows {start_index:g}-{end_index:g}; "
            "saved from web UI"
        )
    if len(fit_points) < 3:
        raise ValueError("Manual fit needs at least 3 selected points.")
    extra = save_fit_outputs(
        file_path,
        parsed,
        fit_points,
        note,
        axis_limits,
        output_to_downloads=output_to_downloads,
    )
    extra["note"] = note
    return sample_payload(file_path, parsed, "ok", extra=extra, fit_points=fit_points)


def export_png_file(
    file_path: Path,
    selected_indices: list,
    axis_limits: dict | None = None,
) -> dict:
    parsed = parse_pyroscience_txt(file_path)
    indices = clean_selected_indices(selected_indices, len(parsed.rows))
    fit_points = [parsed.rows[index] for index in indices]
    if len(fit_points) < 3:
        raise ValueError("PNG export needs at least 3 selected points.")
    fit = linear_fit(fit_points)
    sample_dir = output_dir_for(file_path)
    sample_dir.mkdir(parents=True, exist_ok=True)
    plot_written, plot_path = save_rate_line_png(
        file_path,
        sample_dir,
        parsed.rows,
        fit_points,
        fit,
        axis_limits,
        output_to_downloads=True,
    )
    if not plot_written:
        raise ValueError("PNG export failed. Please check that matplotlib is available.")
    return {
        "plot_written": True,
        "plot_path": str(plot_path),
        "oxygen_rate_umol_L_s": f"{(-fit.slope):.4f}",
        "r2": f"{fit.r2:.4f}",
        "fit_points": str(fit.n),
    }


class OxygenRateHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        if parsed.path == "/":
            return str(STATIC_ROOT / "index.html")
        relative = parsed.path.lstrip("/")
        if relative and ".." not in Path(relative).parts:
            candidate = STATIC_ROOT / relative
            if candidate.exists():
                return str(candidate)
        if parsed.path.startswith("/static/"):
            relative = parsed.path.removeprefix("/static/").lstrip("/")
            return str(STATIC_ROOT / relative)
        return str(STATIC_ROOT / "index.html")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/process-path":
                payload = self.read_json()
                response = process_path(Path(payload["path"]).expanduser())
            elif parsed.path == "/api/upload":
                response = self.handle_upload()
            elif parsed.path == "/api/refit":
                payload = self.read_json()
                selected_indices = payload.get("selected_indices")
                axis_limits = payload.get("axis_limits")
                output_to_downloads = bool(payload.get("download_png"))
                if selected_indices is not None:
                    sample = refit_file(
                        Path(payload["file_path"]),
                        selected_indices=selected_indices,
                        axis_limits=axis_limits,
                        output_to_downloads=output_to_downloads,
                    )
                else:
                    sample = refit_file(
                        Path(payload["file_path"]),
                        int(payload["start_index"]),
                        int(payload["end_index"]),
                        axis_limits=axis_limits,
                        output_to_downloads=output_to_downloads,
                    )
                response = {
                    "sample": sample
                }
            elif parsed.path == "/api/export-png":
                payload = self.read_json()
                response = export_png_file(
                    Path(payload["file_path"]),
                    payload.get("selected_indices", []),
                    payload.get("axis_limits"),
                )
            else:
                self.send_json({"error": "Unknown endpoint."}, HTTPStatus.NOT_FOUND)
                return
            self.send_json(response)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def handle_upload(self) -> dict:
        UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        upload_dir = UPLOAD_ROOT / time.strftime("%Y%m%d_%H%M%S")
        upload_dir.mkdir(parents=True, exist_ok=True)
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type"),
            },
        )
        fields = form["files"] if "files" in form else []
        if not isinstance(fields, list):
            fields = [fields]
        saved_files = []
        for field in fields:
            if not field.filename:
                continue
            filename = safe_name(Path(field.filename).name)
            destination = upload_dir / filename
            with destination.open("wb") as handle:
                shutil.copyfileobj(field.file, handle)
            saved_files.append(destination)
        if not saved_files:
            raise ValueError("No TXT files were uploaded.")
        samples = []
        for file_path in saved_files:
            samples.append(process_file(file_path))
        write_batch_summary(samples, upload_dir)
        return result_payload(samples)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s\n" % (format % args))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), OxygenRateHandler)
    print(f"Oxygen Rate Fit web app: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
