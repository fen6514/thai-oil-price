"""
Draws the PNG pictures for the Thai Finance Daily LINE report.

  table_image(...)  - a clean table (exchange rates, world stock indices)
  line_chart(...)   - a 1-month line chart (gold)

Text inside the pictures is English/numbers only (no Thai font needed).
Needs matplotlib (pip install matplotlib).
"""

import matplotlib

matplotlib.use("Agg")  # draw to files, no screen needed
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402

BG = "#ffffff"
INK = "#1d1d1b"
MUTED = "#77736a"
LINE = "#e6e3dc"
HEAD_BG = "#f6f5f1"
UP = "#1e8449"      # green = went up
DOWN = "#c0392b"    # red = went down
GOLD = "#c9a227"
WIDTH_IN = 10.4     # 1040 px at 100 dpi - fits LINE nicely
DPI = 100

plt.rcParams["font.family"] = "DejaVu Sans"


def change_color(pct):
    if pct is None or abs(pct) < 0.005:
        return MUTED
    return UP if pct > 0 else DOWN


def fmt_pct(pct):
    if pct is None:
        return "-"
    if abs(pct) < 0.005:
        return "0.00%"
    return f"{'▲' if pct > 0 else '▼'} {abs(pct):.2f}%"


def table_image(path, title, subtitle, header, rows, col_widths, footnote=""):
    """
    header: list of column titles (may contain "\\n" for a second line)
    rows:   list of rows; each cell is either text or (text, color)
    col_widths: relative widths, same length as header
    """
    n = len(rows)
    row_h = 0.52
    height = 1.55 + 0.75 + n * row_h + (0.45 if footnote else 0.2)
    fig = plt.figure(figsize=(WIDTH_IN, height), dpi=DPI, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, WIDTH_IN)
    ax.set_ylim(height, 0)  # y grows downward like a page
    ax.axis("off")

    left, right = 0.35, WIDTH_IN - 0.35
    ax.text(left, 0.62, title, fontsize=20, fontweight="bold", color=INK, va="center")
    ax.text(left, 1.12, subtitle, fontsize=11.5, color=MUTED, va="center")

    total = sum(col_widths)
    xs, x = [], left
    for w in col_widths:
        xs.append(x)
        x += (right - left) * w / total
    xs.append(right)

    # header band
    top = 1.55
    ax.add_patch(plt.Rectangle((left, top), right - left, 0.75, color=HEAD_BG, lw=0))
    for i, h in enumerate(header):
        ha, xx = ("left", xs[i] + 0.12) if i == 0 else ("right", xs[i + 1] - 0.12)
        ax.text(xx, top + 0.375, h, fontsize=10.5, color=MUTED, fontweight="bold",
                ha=ha, va="center", linespacing=1.15)

    # rows
    y = top + 0.75
    for r, row in enumerate(rows):
        if r % 2 == 1:
            ax.add_patch(plt.Rectangle((left, y), right - left, row_h, color="#fbfaf7", lw=0))
        for i, cell in enumerate(row):
            text, color = cell if isinstance(cell, tuple) else (cell, INK)
            ha, xx = ("left", xs[i] + 0.12) if i == 0 else ("right", xs[i + 1] - 0.12)
            ax.text(xx, y + row_h / 2, text, fontsize=13, color=color, ha=ha, va="center",
                    fontweight="bold" if i == 0 else "normal")
        y += row_h
        ax.plot([left, right], [y, y], color=LINE, lw=0.8)

    if footnote:
        ax.text(left, y + 0.3, footnote, fontsize=9.5, color=MUTED, va="center")
    fig.savefig(path, dpi=DPI, facecolor=BG)
    plt.close(fig)


def line_chart(path, title, subtitle, points, unit_fmt="{:,.0f}", footnote="", updated=""):
    """points: list of (date, value), oldest first. updated: text shown top-right."""
    dates = [d for d, _ in points]
    vals = [v for _, v in points]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 6.2), dpi=DPI, facecolor=BG)
    fig.subplots_adjust(left=0.1, right=0.95, top=0.80, bottom=0.14 if footnote else 0.1)
    fig.text(0.035, 0.94, title, fontsize=20, fontweight="bold", color=INK, va="center")
    fig.text(0.035, 0.875, subtitle, fontsize=11.5, color=MUTED, va="center")
    if updated:
        fig.text(0.95, 0.94, f"Last update: {updated}", fontsize=12, color=INK,
                 ha="right", va="center")

    ax.plot(dates, vals, color=GOLD, lw=2.6)
    low = min(vals)
    pad = (max(vals) - low) * 0.12 or abs(low) * 0.01 or 1
    ax.fill_between(dates, vals, low - pad, color=GOLD, alpha=0.12)
    ax.set_ylim(low - pad, max(vals) + pad)

    # mark the latest value and the month's high / low
    first, last = vals[0], vals[-1]
    pct = (last / first - 1) * 100 if first else None
    ax.scatter([dates[-1]], [last], color=GOLD, s=50, zorder=3)
    ax.annotate(f"{unit_fmt.format(last)}  ({dates[-1].strftime('%d %b')})", (dates[-1], last),
                textcoords="offset points",
                xytext=(-8, 12), ha="right", fontsize=13, fontweight="bold", color=INK)
    hi_i, lo_i = vals.index(max(vals)), vals.index(low)
    for i, label in ((hi_i, "High"), (lo_i, "Low")):
        if i != len(vals) - 1:
            ax.annotate(f"{label} {unit_fmt.format(vals[i])}", (dates[i], vals[i]),
                        textcoords="offset points", xytext=(0, 10 if label == "High" else -16),
                        ha="center", fontsize=9.5, color=MUTED)
    if pct is not None:
        fig.text(0.95, 0.875, f"1 month: {fmt_pct(pct)}", fontsize=13, fontweight="bold",
                 color=change_color(pct), ha="right", va="center")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=7))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: unit_fmt.format(v)))
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(LINE)
    ax.tick_params(colors=MUTED, labelsize=10)
    ax.grid(axis="y", color=LINE, lw=0.8)
    if footnote:
        fig.text(0.035, 0.03, footnote, fontsize=9.5, color=MUTED)
    fig.savefig(path, dpi=DPI, facecolor=BG)
    plt.close(fig)
