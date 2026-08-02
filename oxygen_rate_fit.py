from __future__ import annotations

import argparse
import csv
import math
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_INPUT = Path(r"G:\Users\19104\Desktop\PTC\oxygen\20260707")
PLOT_DPI = 600


@dataclass
class ParsedData:
    rows: list[tuple[float, float]]
    encoding: str
    time_column: str
    oxygen_column: str


@dataclass
class FitResult:
    slope: float
    intercept: float
    r2: float
    slope_se: float
    start_s: float
    end_s: float
    n: int


@dataclass
class RateCandidate:
    points: list[tuple[float, float]]
    fit: FitResult
    tier_rank: int
    r2_distance: float
    point_count: int
    start_distance: int
    after_turn_points: int
    note: str


def decode_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "gb18030", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\t" in text and "Oxygen" in text:
            return text, encoding
    return raw.decode("latin-1", errors="replace"), "latin-1-replace"


def parse_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def find_column(headers: list[str], required: Iterable[str], preferred: str) -> int:
    required_lower = [item.lower() for item in required]
    preferred_lower = preferred.lower()
    candidates = [
        i
        for i, header in enumerate(headers)
        if all(item in header.lower() for item in required_lower)
    ]
    preferred_candidates = [
        i for i in candidates if preferred_lower in headers[i].lower()
    ]
    if preferred_candidates:
        return preferred_candidates[0]
    if candidates:
        return candidates[0]
    raise ValueError(f"Could not find column containing {required!r}")


def parse_pyroscience_txt(path: Path) -> ParsedData:
    text, encoding = decode_text(path)
    lines = text.splitlines()

    header_index = None
    headers: list[str] = []
    for index, line in enumerate(lines):
        fields = line.rstrip("\r\n").split("\t")
        lowered = [field.strip().lower() for field in fields]
        if any("dt (s)" in field for field in lowered) and any(
            "oxygen" in field for field in lowered
        ):
            header_index = index
            headers = [field.strip() for field in fields]
            break

    if header_index is None:
        raise ValueError("Could not find a data header row with dt(s) and Oxygen.")

    time_index = find_column(headers, ["dt (s)"], "[A Ch.1 Main]")
    oxygen_index = find_column(headers, ["oxygen"], "[A Ch.1 Main]")

    rows: list[tuple[float, float]] = []
    for line in lines[header_index + 1 :]:
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) <= max(time_index, oxygen_index):
            continue
        time_s = parse_float(fields[time_index])
        oxygen = parse_float(fields[oxygen_index])
        if time_s is not None and oxygen is not None:
            rows.append((time_s, oxygen))

    if len(rows) < 3:
        raise ValueError("Not enough numeric oxygen rows were parsed.")

    return ParsedData(
        rows=rows,
        encoding=encoding,
        time_column=headers[time_index],
        oxygen_column=headers[oxygen_index],
    )


def linear_fit(points: list[tuple[float, float]]) -> FitResult:
    if len(points) < 3:
        raise ValueError("Need at least 3 points for a line fit.")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    n = len(points)
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    ssxx = sum((x - x_mean) ** 2 for x in xs)
    if ssxx == 0:
        raise ValueError("All time values are identical.")

    slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / ssxx
    intercept = y_mean - slope * x_mean
    residuals = [y - (slope * x + intercept) for x, y in points]
    ss_res = sum(residual * residual for residual in residuals)
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    r2 = 1.0 if ss_tot == 0 else 1.0 - ss_res / ss_tot
    slope_se = math.sqrt((ss_res / (n - 2)) / ssxx) if n > 2 else math.nan
    return FitResult(slope, intercept, r2, slope_se, xs[0], xs[-1], n)


def find_positive_to_negative_turn_index(
    rows: list[tuple[float, float]], min_center_index: int
) -> int | None:
    for center_index in range(max(1, min_center_index), len(rows) - 1):
        prev_dt = rows[center_index][0] - rows[center_index - 1][0]
        next_dt = rows[center_index + 1][0] - rows[center_index][0]
        if prev_dt == 0 or next_dt == 0:
            continue
        previous_slope = (
            rows[center_index][1] - rows[center_index - 1][1]
        ) / prev_dt
        next_slope = (
            rows[center_index + 1][1] - rows[center_index][1]
        ) / next_dt
        if previous_slope > 0 and next_slope < 0:
            return center_index + 1
    return None


def adjacent_decrease_ratio(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    decreases = sum(
        1 for left, right in zip(points, points[1:]) if right[1] < left[1]
    )
    return decreases / (len(points) - 1)


def adjacent_rates(points: list[tuple[float, float]]) -> list[float]:
    rates = []
    for left, right in zip(points, points[1:]):
        dt = right[0] - left[0]
        if dt <= 0:
            rates.append(math.nan)
        else:
            rates.append((left[1] - right[1]) / dt)
    return rates


def edge_rate_fraction(
    points: list[tuple[float, float]],
    fit_rate: float,
    edge_points: int,
) -> tuple[float, float]:
    rates = [rate for rate in adjacent_rates(points) if math.isfinite(rate)]
    if fit_rate <= 0 or not rates:
        return 0.0, 0.0
    edge_count = max(1, min(edge_points, len(rates) // 2 or 1))
    start_fraction = sum(rates[:edge_count]) / edge_count / fit_rate
    end_fraction = sum(rates[-edge_count:]) / edge_count / fit_rate
    return start_fraction, end_fraction


def first_adjacent_rate_fraction(
    points: list[tuple[float, float]], fit_rate: float
) -> float:
    rates = [rate for rate in adjacent_rates(points) if math.isfinite(rate)]
    if fit_rate <= 0 or not rates:
        return 0.0
    return rates[0] / fit_rate


def half_slope_difference(points: list[tuple[float, float]]) -> float:
    if len(points) < 5:
        return math.inf
    midpoint = len(points) // 2
    if len(points) % 2:
        first_half = points[: midpoint + 1]
        second_half = points[midpoint:]
    else:
        first_half = points[:midpoint]
        second_half = points[midpoint:]
    if len(first_half) < 3 or len(second_half) < 3:
        first_half = points[:3]
        second_half = points[-3:]

    first_rate = -linear_fit(first_half).slope
    second_rate = -linear_fit(second_half).slope
    if first_rate <= 0 or second_rate <= 0:
        return math.inf
    mean_rate = (first_rate + second_rate) / 2
    return abs(first_rate - second_rate) / max(mean_rate, 1e-12)


def find_consumption_peak_index(
    rows: list[tuple[float, float]],
    drop_threshold_umol_l: float,
    drop_confirm_points: int,
    peak_lookback_points: int,
) -> int:
    global_peak_value = max(oxygen for _time_s, oxygen in rows)
    confirm_points = max(3, drop_confirm_points)
    drop_index = None
    for index in range(1, len(rows) - confirm_points + 1):
        window = rows[index : index + confirm_points]
        if global_peak_value - rows[index][1] < drop_threshold_umol_l:
            continue
        if adjacent_decrease_ratio(window) >= 0.8:
            drop_index = index
            break

    if drop_index is None:
        return max(range(len(rows)), key=lambda i: rows[i][1])

    search_start = max(0, drop_index - max(1, peak_lookback_points))
    search_end = max(search_start + 1, drop_index)
    return max(range(search_start, search_end), key=lambda i: rows[i][1])


def choose_rate_line(
    rows: list[tuple[float, float]],
    target_r2: float,
    min_r2: float,
    start_after_turn_points: int,
    start_window_points: int,
    min_start_after_turn_points: int | None,
    max_start_after_turn_points: int | None,
    min_fit_points: int,
    max_fit_points: int,
    min_rate_umol_l_s: float,
    oxygen_floor: float,
    min_descent_ratio: float,
    max_half_slope_diff: float,
    min_start_after_peak_points: int,
    max_start_after_peak_points: int,
    drop_threshold_umol_l: float,
    drop_confirm_points: int,
    peak_lookback_points: int,
    min_edge_rate_fraction: float,
    edge_rate_points: int,
    min_first_rate_fraction: float,
) -> tuple[list[tuple[float, float]], str]:
    peak_index = find_consumption_peak_index(
        rows,
        drop_threshold_umol_l=drop_threshold_umol_l,
        drop_confirm_points=drop_confirm_points,
        peak_lookback_points=peak_lookback_points,
    )
    end_limit_index = len(rows) - 1
    for index, (_time_s, oxygen) in enumerate(rows[peak_index:], start=peak_index):
        if oxygen <= oxygen_floor:
            end_limit_index = index
            break

    min_count = max(3, min_fit_points)
    max_count = max(min_count, max_fit_points)
    tiers: dict[str, list[tuple]] = {"target": [], "min": [], "below": []}
    min_after_peak = max(1, min_start_after_peak_points)
    max_after_peak = max(min_after_peak, max_start_after_peak_points)

    for start_index in range(
        peak_index + min_after_peak,
        min(end_limit_index, peak_index + max_after_peak) + 1,
    ):
        peak_distance = start_index - peak_index
        for count in range(min_count, max_count + 1):
            end_index = start_index + count - 1
            if end_index > end_limit_index:
                break
            points = rows[start_index : end_index + 1]
            fit = linear_fit(points)
            rate = -fit.slope
            if fit.slope >= 0 or rate < min_rate_umol_l_s:
                continue
            descent_ratio = adjacent_decrease_ratio(points)
            if descent_ratio < min_descent_ratio:
                continue
            slope_diff = half_slope_difference(points)
            if slope_diff > max_half_slope_diff:
                continue
            start_rate_fraction, end_rate_fraction = edge_rate_fraction(
                points, rate, edge_rate_points
            )
            if (
                start_rate_fraction < min_edge_rate_fraction
                or end_rate_fraction < min_edge_rate_fraction
            ):
                continue
            first_rate_fraction = first_adjacent_rate_fraction(points, rate)
            if first_rate_fraction < min_first_rate_fraction:
                continue
            item = (
                slope_diff,
                peak_distance,
                len(points),
                abs(fit.r2 - target_r2),
                fit.r2,
                descent_ratio,
                start_rate_fraction,
                end_rate_fraction,
                first_rate_fraction,
                points,
            )
            if fit.r2 >= target_r2:
                tiers["target"].append(item)
            elif fit.r2 >= min_r2:
                tiers["min"].append(item)
            else:
                tiers["below"].append(item)

    def pick_stable(candidates: list[tuple]) -> tuple:
        return min(candidates, key=lambda item: (item[1], item[0], item[2], item[3]))

    def pick_best_below(candidates: list[tuple]) -> tuple:
        return min(candidates, key=lambda item: (-item[4], item[1], item[0], item[2]))

    if tiers["target"]:
        (
            slope_diff,
            peak_distance,
            _count,
            _r2_distance,
            _r2,
            descent_ratio,
            start_rate_fraction,
            end_rate_fraction,
            first_rate_fraction,
            points,
        ) = pick_stable(tiers["target"])
        note = (
            f"rate_line: peak at {rows[peak_index][0]:.3f} s; "
            f"selected stable post-peak falling window with R2 >= {target_r2:g}; "
            f"start +{peak_distance:g} points from peak; "
            f"descent_ratio={descent_ratio:.3f}; half_slope_diff={slope_diff:.3f}; "
            f"edge_rate_fraction={start_rate_fraction:.3f}/{end_rate_fraction:.3f}; "
            f"first_rate_fraction={first_rate_fraction:.3f}"
        )
        return points, note
    if tiers["min"]:
        (
            slope_diff,
            peak_distance,
            _count,
            _r2_distance,
            _r2,
            descent_ratio,
            start_rate_fraction,
            end_rate_fraction,
            first_rate_fraction,
            points,
        ) = pick_stable(tiers["min"])
        note = (
            f"rate_line: peak at {rows[peak_index][0]:.3f} s; "
            f"no window reached R2 >= {target_r2:g}; "
            f"selected stable post-peak falling window with R2 >= {min_r2:g}; "
            f"start +{peak_distance:g} points from peak; "
            f"descent_ratio={descent_ratio:.3f}; half_slope_diff={slope_diff:.3f}; "
            f"edge_rate_fraction={start_rate_fraction:.3f}/{end_rate_fraction:.3f}; "
            f"first_rate_fraction={first_rate_fraction:.3f}"
        )
        return points, note
    if tiers["below"]:
        (
            slope_diff,
            peak_distance,
            _count,
            _r2_distance,
            _r2,
            descent_ratio,
            start_rate_fraction,
            end_rate_fraction,
            first_rate_fraction,
            points,
        ) = pick_best_below(tiers["below"])
        note = (
            f"rate_line: peak at {rows[peak_index][0]:.3f} s; "
            f"no window reached R2 >= {min_r2:g}; "
            f"selected highest-R2 stable post-peak window with minimal curvature; "
            f"start +{peak_distance:g} points from peak; "
            f"descent_ratio={descent_ratio:.3f}; half_slope_diff={slope_diff:.3f}; "
            f"edge_rate_fraction={start_rate_fraction:.3f}/{end_rate_fraction:.3f}; "
            f"first_rate_fraction={first_rate_fraction:.3f}"
        )
        return points, note
    raise ValueError("No stable post-peak falling rate-line candidate could be selected.")


def list_rate_line_candidates(
    rows: list[tuple[float, float]],
    target_r2: float,
    min_r2: float,
    start_after_turn_points: int,
    min_start_after_turn_points: int,
    max_start_after_turn_points: int,
    min_fit_points: int,
    max_fit_points: int,
    min_rate_umol_l_s: float,
    oxygen_floor: float,
    note_prefix: str,
) -> list[RateCandidate]:
    peak_index = max(range(len(rows)), key=lambda i: rows[i][1])
    end_limit = rows[-1][0]
    for time_s, oxygen in rows[peak_index:]:
        if oxygen <= oxygen_floor:
            end_limit = time_s
            break

    turn_index = find_positive_to_negative_turn_index(
        rows, min_center_index=max(1, peak_index - 3)
    )
    if turn_index is None:
        turn_index = peak_index + 1
        start_note = "no slope turn found; used peak as fallback"
    else:
        start_note = f"slope turn at {rows[turn_index][0]:.3f} s"

    min_after = max(1, min_start_after_turn_points)
    max_after = max(min_after, max_start_after_turn_points)
    min_count = max(3, min_fit_points)
    max_count = max(min_count, max_fit_points)
    candidates: list[RateCandidate] = []

    for after_turn_points in range(min_after, max_after + 1):
        start_index = turn_index + after_turn_points
        if start_index >= len(rows) or rows[start_index][0] > end_limit:
            continue
        start_distance = abs(after_turn_points - start_after_turn_points)
        for count in range(min_count, max_count + 1):
            end_index = start_index + count - 1
            if end_index >= len(rows) or rows[end_index][0] > end_limit:
                break
            points = rows[start_index : end_index + 1]
            if points[0][1] <= points[-1][1]:
                continue
            fit = linear_fit(points)
            rate = -fit.slope
            if fit.slope >= 0 or rate < min_rate_umol_l_s:
                continue
            if fit.r2 >= target_r2:
                tier_rank = 0
                tier_note = f"R2 >= {target_r2:g}"
            elif fit.r2 >= min_r2:
                tier_rank = 1
                tier_note = f"R2 >= {min_r2:g}"
            else:
                tier_rank = 2
                tier_note = f"closest R2 below {min_r2:g}"
            note = (
                f"{note_prefix}: {start_note}; start +{after_turn_points} points; "
                f"selected under concentration-trend constraint; {tier_note}"
            )
            candidates.append(
                RateCandidate(
                    points=points,
                    fit=fit,
                    tier_rank=tier_rank,
                    r2_distance=abs(fit.r2 - target_r2),
                    point_count=len(points),
                    start_distance=start_distance,
                    after_turn_points=after_turn_points,
                    note=note,
                )
            )
    return candidates


def safe_name(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", text).strip("_") or "sample"


def iter_input_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(input_path)
    files = []
    for path in sorted(input_path.rglob("*.txt")):
        if "ChannelData" in path.parts:
            continue
        if path.name.lower() in {"statuslegend.txt"}:
            continue
        files.append(path)
    return files


def write_selected_csv(path: Path, rows: list[tuple[float, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_s", "oxygen_umol_L"])
        writer.writerows(rows)


def write_rate_line_csv(
    path: Path,
    all_rows: list[tuple[float, float]],
    fit_points: list[tuple[float, float]],
    fit: FitResult,
) -> None:
    fit_point_keys = {(time_s, oxygen) for time_s, oxygen in fit_points}
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["time_s", "oxygen_umol_L", "in_fit_window", "oxygen_fit_umol_L"]
        )
        for time_s, oxygen in all_rows:
            in_fit_window = (time_s, oxygen) in fit_point_keys
            fitted = fit.slope * time_s + fit.intercept if in_fit_window else ""
            writer.writerow([time_s, oxygen, in_fit_window, fitted])


def finite_axis_value(axis_limits: dict | None, key: str) -> float | None:
    if not axis_limits:
        return None
    try:
        value = float(axis_limits[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def save_plot(
    path: Path,
    all_rows: list[tuple[float, float]],
    fit_points: list[tuple[float, float]],
    fit: FitResult,
    axis_limits: dict | None = None,
) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False

    all_x = [point[0] for point in all_rows]
    all_y = [point[1] for point in all_rows]
    fit_x = [point[0] for point in fit_points]
    fit_y = [point[1] for point in fit_points]
    line_y = [fit.slope * x + fit.intercept for x in fit_x]

    fig, ax = plt.subplots(figsize=(8.5, 5.2), dpi=PLOT_DPI)
    ax.plot(
        all_x,
        all_y,
        color="#2f6f8f",
        linewidth=1.2,
        marker="o",
        markersize=2.0,
        markerfacecolor="#2f6f8f",
        markeredgewidth=0,
        alpha=0.92,
        label="Selected data",
    )
    ax.scatter(fit_x, fit_y, color="#d9822b", s=16, label="Fit window", zorder=3)
    ax.plot(fit_x, line_y, color="#b42318", linewidth=2.0, label="Linear fit")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Oxygen (umol/L)")
    ax.set_title(
        f"Oxygen-rate fit: {(-fit.slope):.4f} umol/L/s, R2={fit.r2:.4f}"
    )
    x_min = finite_axis_value(axis_limits, "xmin")
    x_max = finite_axis_value(axis_limits, "xmax")
    y_min = finite_axis_value(axis_limits, "ymin")
    y_max = finite_axis_value(axis_limits, "ymax")
    if x_min is not None or x_max is not None:
        left, right = ax.get_xlim()
        left = x_min if x_min is not None else left
        right = x_max if x_max is not None else right
        if right > left:
            ax.set_xlim(left, right)
    if y_min is not None or y_max is not None:
        bottom, top = ax.get_ylim()
        bottom = y_min if y_min is not None else bottom
        top = y_max if y_max is not None else top
        if top > bottom:
            ax.set_ylim(bottom, top)
    ax.grid(True, color="#d0d7de", linewidth=0.6, alpha=0.8)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=PLOT_DPI, format="png")
    plt.close(fig)
    return True


def downloads_dir() -> Path:
    if sys.platform.startswith("win"):
        try:
            import winreg

            value_names = ("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads")
            key_paths = (
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            )
            for key_path in key_paths:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                        for value_name in value_names:
                            try:
                                raw_path, _kind = winreg.QueryValueEx(key, value_name)
                            except OSError:
                                continue
                            candidate = Path(os.path.expandvars(str(raw_path)))
                            if candidate:
                                candidate.mkdir(parents=True, exist_ok=True)
                                return candidate
                except OSError:
                    continue
        except Exception:
            pass

    user_profile = os.environ.get("USERPROFILE")
    candidates = []
    if user_profile:
        candidates.append(Path(user_profile) / "Downloads")
    candidates.append(Path.home() / "Downloads")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    target = candidates[0]
    target.mkdir(parents=True, exist_ok=True)
    return target


def save_rate_line_png(
    input_file: Path,
    sample_dir: Path,
    all_rows: list[tuple[float, float]],
    fit_points: list[tuple[float, float]],
    fit: FitResult,
    axis_limits: dict | None = None,
    output_to_downloads: bool = False,
) -> tuple[bool, Path]:
    sample_plot_path = sample_dir / "rate_line.png"
    plot_path = (
        downloads_dir() / f"{safe_name(input_file.stem)}_rate_line.png"
        if output_to_downloads
        else sample_plot_path
    )
    plot_written = save_plot(plot_path, all_rows, fit_points, fit, axis_limits)
    if plot_written and output_to_downloads:
        sample_plot_path = sample_dir / "rate_line.png"
        if plot_path.resolve() != sample_plot_path.resolve():
            shutil.copy2(plot_path, sample_plot_path)
    return plot_written, plot_path


def build_summary_text(input_path: Path, parsed: ParsedData, fit: FitResult, note: str) -> str:
    rate = -fit.slope
    lines = [
        "Oxygen-rate fitting result",
        "==========================",
        f"拟合范围: {fit.start_s:.3f} - {fit.end_s:.3f} s",
        f"拟合点数: {fit.n}",
        f"斜率: {fit.slope:.4f} umol/L/s",
        f"oxygen-rate: {rate:.4f} umol/L/s",
        f"截距: {fit.intercept:.4f} umol/L",
        f"R^2: {fit.r2:.4f}",
        "",
        "Details",
        "-------",
        f"Input: {input_path}",
        f"Selected time column: {parsed.time_column}",
        f"Selected oxygen column: {parsed.oxygen_column}",
        f"Total selected rows: {len(parsed.rows)}",
        f"Fit selection: {note}",
        f"Slope standard error (umol/L/s): {fit.slope_se:.4f}",
    ]
    return "\n".join(lines) + "\n"


def write_skip_summary(sample_dir: Path, input_file: Path, reason: str) -> None:
    sample_dir.mkdir(parents=True, exist_ok=True)
    for stale_name in ("selected_oxygen_data.csv", "rate_line_points.csv", "rate_line.png"):
        stale_path = sample_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()
    lines = [
        "Oxygen-rate fitting result",
        "==========================",
        "状态: skipped",
        f"原因: {reason}",
        "",
        "Details",
        "-------",
        f"Input: {input_file}",
    ]
    (sample_dir / "rate_line_summary.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8-sig"
    )


def process_one(input_file: Path, output_dir: Path, args: argparse.Namespace) -> dict[str, str]:
    parsed = parse_pyroscience_txt(input_file)
    fit_points, note = choose_rate_line(
        parsed.rows,
        target_r2=args.target_r2,
        min_r2=args.min_r2,
        start_after_turn_points=args.start_after_turn_points,
        start_window_points=args.start_window_points,
        min_start_after_turn_points=args.min_start_after_turn_points,
        max_start_after_turn_points=args.max_start_after_turn_points,
        min_fit_points=args.min_fit_points,
        max_fit_points=args.max_fit_points,
        min_rate_umol_l_s=args.min_rate,
        oxygen_floor=args.oxygen_floor,
        min_descent_ratio=args.min_descent_ratio,
        max_half_slope_diff=args.max_half_slope_diff,
        min_start_after_peak_points=args.min_start_after_peak_points,
        max_start_after_peak_points=args.max_start_after_peak_points,
        drop_threshold_umol_l=args.drop_threshold,
        drop_confirm_points=args.drop_confirm_points,
        peak_lookback_points=args.peak_lookback_points,
        min_edge_rate_fraction=args.min_edge_rate_fraction,
        edge_rate_points=args.edge_rate_points,
        min_first_rate_fraction=args.min_first_rate_fraction,
    )
    fit = linear_fit(fit_points)

    sample_dir = output_dir / safe_name(input_file.parent.name)
    sample_dir.mkdir(parents=True, exist_ok=True)
    write_selected_csv(sample_dir / "selected_oxygen_data.csv", parsed.rows)
    write_rate_line_csv(sample_dir / "rate_line_points.csv", parsed.rows, fit_points, fit)
    plot_written, plot_path = save_rate_line_png(
        input_file, sample_dir, parsed.rows, fit_points, fit
    )
    summary_text = build_summary_text(input_file, parsed, fit, note)
    (sample_dir / "rate_line_summary.txt").write_text(summary_text, encoding="utf-8-sig")

    return {
        "sample": input_file.parent.name,
        "input_file": str(input_file),
        "fit_start_s": f"{fit.start_s:.3f}",
        "fit_end_s": f"{fit.end_s:.3f}",
        "fit_points": str(fit.n),
        "slope_umol_L_s": f"{fit.slope:.4f}",
        "oxygen_rate_umol_L_s": f"{(-fit.slope):.4f}",
        "intercept_umol_L": f"{fit.intercept:.4f}",
        "r2": f"{fit.r2:.4f}",
        "plot_written": str(plot_written),
        "plot_path": str(plot_path),
        "output_dir": str(sample_dir),
        "note": note,
        "status": "ok",
        "error": "",
    }


def parse_primary_concentration(sample: str) -> int | None:
    match = re.search(r"_(80|100|120|150)$", sample)
    return int(match.group(1)) if match else None


def trend_candidate_key(candidate: RateCandidate) -> tuple[float, ...]:
    return (
        float(candidate.tier_rank),
        candidate.r2_distance,
        float(candidate.point_count),
        float(candidate.start_distance),
        float(candidate.after_turn_points),
    )


def trend_path_score(candidates: list[RateCandidate]) -> tuple[float, ...]:
    return (
        float(max(candidate.tier_rank for candidate in candidates)),
        float(sum(candidate.tier_rank for candidate in candidates)),
        sum(candidate.r2_distance for candidate in candidates),
        float(sum(candidate.point_count for candidate in candidates)),
        float(sum(candidate.start_distance for candidate in candidates)),
    )


def select_monotonic_trend(
    candidates_by_concentration: dict[int, list[RateCandidate]],
    concentrations: list[int],
    rate_tolerance: float,
) -> dict[int, RateCandidate] | None:
    states: list[tuple[list[RateCandidate], tuple[float, ...]]] = []
    first_concentration = concentrations[0]
    for candidate in candidates_by_concentration[first_concentration]:
        states.append(([candidate], trend_path_score([candidate])))

    for concentration in concentrations[1:]:
        new_states: list[tuple[list[RateCandidate], tuple[float, ...]]] = []
        for path, _score in states:
            previous_rate = -path[-1].fit.slope
            for candidate in candidates_by_concentration[concentration]:
                rate = -candidate.fit.slope
                if previous_rate <= rate + rate_tolerance:
                    new_path = [*path, candidate]
                    new_states.append((new_path, trend_path_score(new_path)))
        if not new_states:
            return None
        states = sorted(new_states, key=lambda item: item[1])[:5000]

    selected_path = min(states, key=lambda item: item[1])[0]
    return dict(zip(concentrations, selected_path))


def apply_concentration_trend(
    rows: list[dict[str, str]], output_dir: Path, args: argparse.Namespace
) -> list[dict[str, str]]:
    concentrations = [80, 100, 120, 150]
    entries: dict[int, tuple[int, dict[str, str]]] = {}
    for index, row in enumerate(rows):
        if row["status"] != "ok":
            continue
        concentration = parse_primary_concentration(row["sample"])
        if concentration in concentrations and concentration not in entries:
            entries[concentration] = (index, row)

    if any(concentration not in entries for concentration in concentrations):
        return rows

    parsed_by_concentration: dict[int, ParsedData] = {}
    candidates_by_concentration: dict[int, list[RateCandidate]] = {}
    min_after = max(1, args.start_after_turn_points - args.start_window_points)
    for concentration in concentrations:
        _index, row = entries[concentration]
        input_file = Path(row["input_file"])
        parsed = parse_pyroscience_txt(input_file)
        parsed_by_concentration[concentration] = parsed
        candidates = list_rate_line_candidates(
            parsed.rows,
            target_r2=args.target_r2,
            min_r2=args.min_r2,
            start_after_turn_points=args.start_after_turn_points,
            min_start_after_turn_points=min_after,
            max_start_after_turn_points=args.trend_max_start_after_turn_points,
            min_fit_points=args.min_fit_points,
            max_fit_points=args.max_fit_points,
            min_rate_umol_l_s=args.min_rate,
            oxygen_floor=args.oxygen_floor,
            note_prefix="rate_line trend-adjusted",
        )
        if not candidates:
            return rows
        candidates_by_concentration[concentration] = sorted(
            candidates, key=trend_candidate_key
        )[: args.trend_candidate_limit]

    selected = select_monotonic_trend(
        candidates_by_concentration,
        concentrations,
        rate_tolerance=args.trend_rate_tolerance,
    )
    if selected is None:
        return rows

    for concentration in concentrations:
        index, row = entries[concentration]
        input_file = Path(row["input_file"])
        parsed = parsed_by_concentration[concentration]
        candidate = selected[concentration]
        fit = candidate.fit
        sample_dir = output_dir / safe_name(input_file.parent.name)
        sample_dir.mkdir(parents=True, exist_ok=True)
        write_selected_csv(sample_dir / "selected_oxygen_data.csv", parsed.rows)
        write_rate_line_csv(
            sample_dir / "rate_line_points.csv", parsed.rows, candidate.points, fit
        )
        plot_written, plot_path = save_rate_line_png(
            input_file, sample_dir, parsed.rows, candidate.points, fit
        )
        summary_text = build_summary_text(input_file, parsed, fit, candidate.note)
        (sample_dir / "rate_line_summary.txt").write_text(
            summary_text, encoding="utf-8-sig"
        )
        row.update(
            {
                "fit_start_s": f"{fit.start_s:.3f}",
                "fit_end_s": f"{fit.end_s:.3f}",
                "fit_points": str(fit.n),
                "slope_umol_L_s": f"{fit.slope:.4f}",
                "oxygen_rate_umol_L_s": f"{(-fit.slope):.4f}",
                "intercept_umol_L": f"{fit.intercept:.4f}",
                "r2": f"{fit.r2:.4f}",
                "plot_written": str(plot_written),
                "plot_path": str(plot_path),
                "output_dir": str(sample_dir),
                "note": candidate.note,
                "status": "ok",
                "error": "",
            }
        )
        rows[index] = row
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=Path("oxygen_rate_fit_output_20260707"))
    parser.add_argument("--target-r2", type=float, default=0.9999)
    parser.add_argument("--min-r2", type=float, default=0.999)
    parser.add_argument("--start-after-turn-points", type=int, default=6)
    parser.add_argument("--start-window-points", type=int, default=3)
    parser.add_argument("--min-start-after-turn-points", type=int, default=None)
    parser.add_argument("--max-start-after-turn-points", type=int, default=None)
    parser.add_argument("--min-fit-points", type=int, default=5)
    parser.add_argument("--max-fit-points", type=int, default=20)
    parser.add_argument("--oxygen-floor", type=float, default=45.0)
    parser.add_argument("--min-rate", type=float, default=1.0)
    parser.add_argument("--min-descent-ratio", type=float, default=0.8)
    parser.add_argument("--max-half-slope-diff", type=float, default=0.3)
    parser.add_argument("--min-start-after-peak-points", type=int, default=2)
    parser.add_argument("--max-start-after-peak-points", type=int, default=6)
    parser.add_argument("--drop-threshold", type=float, default=2.0)
    parser.add_argument("--drop-confirm-points", type=int, default=5)
    parser.add_argument("--peak-lookback-points", type=int, default=5)
    parser.add_argument("--min-edge-rate-fraction", type=float, default=0.45)
    parser.add_argument("--edge-rate-points", type=int, default=2)
    parser.add_argument("--min-first-rate-fraction", type=float, default=0.7)
    parser.add_argument("--trend-max-start-after-turn-points", type=int, default=30)
    parser.add_argument("--trend-candidate-limit", type=int, default=250)
    parser.add_argument("--trend-rate-tolerance", type=float, default=0.0)
    parser.add_argument(
        "--no-enforce-concentration-trend",
        dest="enforce_concentration_trend",
        action="store_false",
    )
    parser.set_defaults(enforce_concentration_trend=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    files = iter_input_files(input_path)
    if not files:
        raise SystemExit(f"No txt files found in {input_path}")

    rows = []
    for file_path in files:
        try:
            row = process_one(file_path, output_dir, args)
        except Exception as exc:
            sample_dir = output_dir / safe_name(file_path.parent.name)
            write_skip_summary(sample_dir, file_path, str(exc))
            row = {
                "sample": file_path.parent.name,
                "input_file": str(file_path),
                "fit_start_s": "",
                "fit_end_s": "",
                "fit_points": "",
                "slope_umol_L_s": "",
                "oxygen_rate_umol_L_s": "",
                "intercept_umol_L": "",
                "r2": "",
                "plot_written": "False",
                "plot_path": "",
                "output_dir": str(sample_dir),
                "note": "skipped: no candidate matched the falling segment and minimum rate rules",
                "status": "skipped",
                "error": str(exc),
            }
        rows.append(row)

    if args.enforce_concentration_trend:
        rows = apply_concentration_trend(rows, output_dir, args)

    summary_path = output_dir / "batch_summary.csv"
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
        writer.writerows(rows)

    ok_count = sum(row["status"] == "ok" for row in rows)
    print(f"Processed {ok_count}/{len(rows)} txt files.")
    print(f"Wrote: {summary_path}")
    for row in rows:
        if row["status"] == "ok":
            print(
                f"{row['sample']}: rate={row['oxygen_rate_umol_L_s']} umol/L/s, "
                f"R2={row['r2']}, points={row['fit_points']}"
            )
        elif row["status"] == "skipped":
            print(f"{row['sample']}: SKIPPED {row['error']}")
        else:
            print(f"{row['sample']}: ERROR {row['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
