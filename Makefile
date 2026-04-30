.PHONY: setup build run reconstruct clean clean-images clean-output logs help

help:
	@echo "Usage:"
	@echo "  make setup        Create input/ images/ output/ directories"
	@echo "  make build        Build Docker images"
	@echo "  make run          Run preprocess + OCR pipeline"
	@echo "  make reconstruct  Run reconstruct_layout + find_sections"
	@echo "  make logs         Tail docker compose logs"
	@echo "  make clean        Remove intermediate images and output"
	@echo "  make clean-images Remove intermediate PNGs only"
	@echo "  make clean-output Remove OCR output only"

setup:
	mkdir -p input images output

build:
	docker compose build

run: setup
	docker compose up

reconstruct: setup
	docker compose --profile reconstruct up

logs:
	docker compose logs -f

clean: clean-images clean-output

clean-images:
	rm -rf images/*

clean-output:
	rm -rf output/*
