.PHONY: setup build build-no-cache rebuild run reconstruct audio lessons clean clean-images clean-output logs help

help:
	@echo "Usage:"
	@echo "  make setup        Create input/ images/ output/ directories"
	@echo "  make build        Build Docker images"
	@echo "  make build-no-cache  Build Docker images without cache"
	@echo "  make rebuild      Build without cache, then run"
	@echo "  make run          Run preprocess + OCR pipeline"
	@echo "  make reconstruct  Run reconstruct_layout + find_sections"
	@echo "  make audio        Convert lesson dialogs/sentences to MP3 via edge-tts"
	@echo "  make lessons      Parse OCR output into lesson markdown files"
	@echo "  make logs         Tail docker compose logs"
	@echo "  make clean        Remove intermediate images and output"
	@echo "  make clean-images Remove intermediate PNGs only"
	@echo "  make clean-output Remove OCR output only"

setup:
	mkdir -p input images output models audio

build:
	docker compose build

build-no-cache:
	docker compose build --no-cache

rebuild: build-no-cache run

run: setup
	docker compose up

reconstruct: setup
	docker compose --profile reconstruct up

audio: setup
	docker compose --profile tts up tts

lessons: setup
	mkdir -p lessons
	python3 reconstruct/parse_lessons.py output lessons

logs:
	docker compose logs -f

clean: clean-images clean-output

clean-images:
	rm -rf images/*

clean-output:
	rm -rf output/*
