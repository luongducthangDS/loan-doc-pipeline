# Trên Windows không có make: chạy trực tiếp các lệnh python bên dưới (xem README).
PY ?= python
SEED ?= 42
SPLIT ?= dev
EXTRACTOR ?= oracle

.PHONY: install test data data-fast eval eval-fast check

install:
	$(PY) -m pip install -r requirements.txt

test:
	$(PY) -m pytest -q

data:            ## sinh dev 50 + test 300 kèm ảnh -> data/synthetic/
	$(PY) -m datagen.build --seed $(SEED)

data-fast:       ## chỉ manifest, không ảnh (vài chục giây) -> data/synthetic-fast/
	$(PY) -m datagen.build --seed $(SEED) --no-images --out data/synthetic-fast

eval:            ## -> reports/<run_id>/report.md, metrics.json, errors.csv
	$(PY) -m loanpipe.evaluate --split $(SPLIT) --extractor $(EXTRACTOR)

eval-fast:
	$(PY) -m loanpipe.evaluate --split $(SPLIT) --extractor $(EXTRACTOR) --data data/synthetic-fast --no-file-check

check:           ## chặn file ảnh/PDF nằm ngoài data/synthetic/
	$(PY) scripts/check_data_paths.py
