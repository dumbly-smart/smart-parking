# Deterministic software demonstration

1. Activate the project environment and start the API with `make run`.
2. Open `http://127.0.0.1:8000/dashboard`.
3. Run `python -m scripts.run_simulated_demo --base-url http://127.0.0.1:8000 --rfid-uid DEMO-CARD-001 --idempotency-key demo-entry-001`.
4. Show the entry assignment, slot state, optimizer comparison, forecast, and dashboard animation. Use a new idempotency key for each new demo entry.
5. For the physical tabletop demo, scan a dedicated test tag. Keep fingers clear of the servo arm and confirm each status response before describing a gate action.

The software demo uses a synthetic RFID value. It does not represent a physical tag read.
