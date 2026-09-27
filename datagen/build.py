"""Sinh bộ dữ liệu: data/{dev,test}/<app_id>/{truth.json, *.jpg}.

    python -m datagen.build --n 500 --seed 42
Chia tập cố định theo index (i % 5 in {0,1} -> test, 40%). Test set: KHÔNG nhìn khi tune prompt.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from datagen.render import render
from datagen.truth import generate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("data"))
    ap.add_argument("--no-render", action="store_true", help="chỉ sinh truth.json")
    ap.add_argument("--start", type=int, default=0, help="bỏ qua hồ sơ có index < start (chạy tiếp)")
    args = ap.parse_args()

    stats: Counter = Counter()
    for i, app in enumerate(generate(args.n, args.seed)):
        noise_rng = random.Random(f"{args.seed}-{i}")  # rng riêng mỗi hồ sơ -> chạy tiếp vẫn tái lập
        split = "test" if i % 5 in (0, 1) else "dev"
        stats[(split, app.case.value)] += 1
        for code in app.errors + app.benign:
            stats[(split, code.value)] += 1
        if i < args.start:
            continue
        d = args.out / split / app.app_id
        d.mkdir(parents=True, exist_ok=True)
        noise = {} if args.no_render else render(app, d, noise_rng)
        payload = json.loads(app.model_dump_json()) | {"noise": noise}
        (d / "truth.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    for (split, k), v in sorted(stats.items()):
        print(f"{split:5} {k:24} {v}")


if __name__ == "__main__":
    main()
