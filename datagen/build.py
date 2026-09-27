"""Sinh bộ dữ liệu synthetic: data/synthetic/{dev,test}/<bundle_id>/*.jpg + manifest.jsonl.

    python -m datagen.build --seed 42                 # dev 50 + test 300, đủ ảnh
    python -m datagen.build --seed 42 --no-images     # chỉ manifest (có raw), ~vài giây; dùng cho CI
    python -m datagen.build --seed 42 --split dev

- Tái lập: cùng seed -> cùng nhãn, cùng raw. Ảnh có thể khác chút giữa máy do font hệ điều hành.
- Chạy tiếp được: bộ nào đã có bundle.json thì bỏ qua.
- Test đóng băng (spec mục 9): đã có test/manifest.jsonl thì từ chối ghi đè, trừ khi --force.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

from datagen import profiles as P
from datagen.augment import JPEG_QUALITY, LEVELS, augment
from datagen.render import render_bundle
from datagen.truth import DOC_IDS, generate_bundle, plan
from loanpipe.schemas import DocType

SPLITS = {"dev": {"n": 50, "layouts": "AB"}, "test": {"n": 300, "layouts": "ABC"}}


def _file_names(dt: DocType, n_pages: int) -> list[str]:
    if dt is DocType.CCCD:
        return ["cccd_front.jpg", "cccd_back.jpg"]
    return [f"{dt.value}.jpg"] if n_pages == 1 else [f"{dt.value}_p{i}.jpg" for i in range(1, n_pages + 1)]


def build_split(split: str, n: int, seed: int, out: Path | None, images: bool) -> list[dict]:
    rng = random.Random(f"{seed}-{split}")
    entries = []
    for i, (errs, nms) in enumerate(plan(n, rng)):
        bundle_id = f"{split}_{i:04d}"
        truth = generate_bundle(rng, bundle_id, errs, nms)  # truth sinh tuần tự -> luôn tái lập
        bdir = out / split / bundle_id if images else None
        cached = bdir / "bundle.json" if images else None
        if images and cached.exists():
            try:
                entries.append(json.loads(cached.read_text("utf-8")))
                continue
            except json.JSONDecodeError:  # bị ngắt khi đang ghi -> sinh lại bộ này
                pass
        rseed = f"{seed}-{split}-{i}"
        rrng = random.Random(rseed)  # rng riêng mỗi bộ -> chạy tiếp vẫn ra đúng ảnh cũ
        layouts = {"cccd": "A", **{d: rrng.choice(SPLITS[split]["layouts"]) for d in ("don_vay", "hdld", "sao_ke")}}
        level = rrng.choice(LEVELS)
        bank = rrng.choice(P.NGAN_HANG)
        docs = []
        for rd in render_bundle(truth, layouts, bank, rrng):
            files = _file_names(rd.doc_type, len(rd.pages))
            if images:
                bdir.mkdir(parents=True, exist_ok=True)
                for page, name in zip(rd.pages, files):
                    augment(page, level, rrng).save(bdir / name, quality=JPEG_QUALITY[level])
            docs.append({
                "doc_id": DOC_IDS[rd.doc_type], "type": rd.doc_type.value,
                "files": [f"{bundle_id}/{f}" for f in files],
                "fields_gt": truth.docs[rd.doc_type].model_dump(mode="json"),
                "fields_raw": {k: {"raw": r, "page": p} for k, (r, p) in rd.raw.items()},
            })
        errors, near = truth.labels()
        entry = {"bundle_id": bundle_id, "split": split, "seed": rseed, "layout_ids": layouts,
                 "augment": level, "bank": bank, "docs": docs,
                 "missing_docs": [d.value for d in truth.missing],
                 "injected_errors": errors, "near_miss": near, "expected_route": truth.expected_route}
        if images:  # ghi nguyên tử: bundle.json chỉ tồn tại khi ảnh và metadata đã đủ
            tmp = cached.with_suffix(".tmp")
            tmp.write_text(json.dumps(entry, ensure_ascii=False), "utf-8")
            os.replace(tmp, cached)
        entries.append(entry)
        if images and (i + 1) % 25 == 0:
            print(f"  {split}: {i + 1}/{n}", flush=True)
    return entries


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--split", choices=[*SPLITS, "all"], default="all")
    ap.add_argument("--n", type=int, help="ghi đè số bộ (mặc định dev 50, test 300)")
    ap.add_argument("--out", type=Path, default=Path("data/synthetic"))
    ap.add_argument("--no-images", action="store_true", help="chỉ ghi manifest (raw vẫn có), không vẽ ảnh")
    ap.add_argument("--force", action="store_true", help="cho phép ghi đè test set đã đóng băng")
    args = ap.parse_args()

    for split in SPLITS if args.split == "all" else [args.split]:
        man = args.out / split / "manifest.jsonl"
        if split == "test" and man.exists() and not args.force:
            print(f"test set đã đóng băng ({man}); bỏ qua. Dùng --force nếu chắc chắn.", file=sys.stderr)
            continue
        n = args.n or SPLITS[split]["n"]
        entries = build_split(split, n, args.seed, args.out, images=not args.no_images)
        man.parent.mkdir(parents=True, exist_ok=True)
        tmp = man.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), "utf-8")
        os.replace(tmp, man)
        stats = Counter(e["expected_route"] for e in entries)
        codes = Counter(x["code"] for e in entries for x in e["injected_errors"] + e["near_miss"])
        print(f"{split}: {len(entries)} bộ -> {man}")
        print("  route:", dict(stats))
        print("  nhãn :", dict(sorted(codes.items())))


if __name__ == "__main__":
    main()
