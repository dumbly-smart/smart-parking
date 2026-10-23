"""Capture a camera JPEG and interactively calibrate parking-slot ROIs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import yaml
from PIL import Image, ImageDraw, ImageTk

from vision.models import RoiConfig

DEFAULT_CAMERA_URL = "http://esp32-cam.local/capture"
MAX_CAMERA_JPEG_BYTES = 5 * 1024 * 1024


def build_roi_config(
    *,
    image_size: tuple[int, int],
    slot_ids: tuple[int, ...],
    rectangles: dict[int, tuple[int, int, int, int]],
    heuristic: dict[str, float | int],
) -> dict[str, object]:
    width, height = image_size
    if width <= 0 or height <= 0 or not slot_ids or set(rectangles) != set(slot_ids):
        raise ValueError("each configured slot needs exactly one ROI")
    slots = []
    for slot_id in slot_ids:
        x, y, roi_width, roi_height = rectangles[slot_id]
        if x < 0 or y < 0 or roi_width <= 0 or roi_height <= 0:
            raise ValueError("ROI coordinates and dimensions must be positive")
        if x + roi_width > width or y + roi_height > height:
            raise ValueError(f"ROI for slot {slot_id} is outside image bounds")
        slots.append(
            {
                "slot_id": slot_id,
                "x": x,
                "y": y,
                "width": roi_width,
                "height": roi_height,
            }
        )

    for index, first in enumerate(slots):
        for second in slots[index + 1 :]:
            overlap_x = max(first["x"], second["x"]) < min(
                first["x"] + first["width"], second["x"] + second["width"]
            )
            overlap_y = max(first["y"], second["y"]) < min(
                first["y"] + first["height"], second["y"] + second["height"]
            )
            if overlap_x and overlap_y:
                raise ValueError(
                    f"ROIs for slots {first['slot_id']} and {second['slot_id']} overlap"
                )

    result: dict[str, object] = {"heuristic": heuristic, "slots": slots}
    RoiConfig.model_validate(result)
    return result


def capture_jpeg(
    url: str, *, timeout: float = 5.0, maximum_bytes: int = 5 * 1024 * 1024
) -> Image.Image:
    if not url.startswith(("http://", "https://")):
        raise ValueError("camera URL must use HTTP or HTTPS")
    if timeout <= 0:
        raise ValueError("camera timeout must be positive")
    if maximum_bytes <= 0 or maximum_bytes > MAX_CAMERA_JPEG_BYTES:
        raise ValueError("camera image size limit must be between 1 byte and 5 MiB")
    with urlopen(Request(url, headers={"Accept": "image/jpeg"}), timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type != "image/jpeg":
            raise ValueError("camera did not return image/jpeg")
        payload = response.read(maximum_bytes + 1)
    if not payload or len(payload) > maximum_bytes:
        raise ValueError("camera image is empty or exceeds the configured size limit")
    from io import BytesIO

    with Image.open(BytesIO(payload)) as image:
        if image.format != "JPEG":
            raise ValueError("camera payload is not a valid JPEG")
        image.verify()
    result = Image.open(BytesIO(payload)).convert("RGB")
    return result


class RoiCalibrationWindow:
    def __init__(
        self,
        image: Image.Image,
        slot_ids: tuple[int, ...],
        heuristic: dict[str, float | int],
        output_path: Path,
        overlay_path: Path,
    ) -> None:
        import tkinter as tk
        from tkinter import messagebox

        self.tk = tk
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.root.title("Smart Parking ROI calibration")
        screen_width = max(320, self.root.winfo_screenwidth() - 80)
        screen_height = max(300, self.root.winfo_screenheight() - 180)
        self.scale = min(1.0, screen_width / image.width, screen_height / image.height)
        display_size = (int(image.width * self.scale), int(image.height * self.scale))
        self.source_image = image
        self.preview = image.resize(display_size)
        self.photo = ImageTk.PhotoImage(self.preview)
        self.slot_ids = slot_ids
        self.heuristic = heuristic
        self.output_path = output_path
        self.overlay_path = overlay_path
        self.rectangles: dict[int, tuple[int, int, int, int]] = {}
        self.active_slot_index = 0
        self.drag_start: tuple[float, float] | None = None
        self.preview_rect = None

        self.instruction = tk.StringVar()
        tk.Label(self.root, textvariable=self.instruction, anchor="w").pack(fill="x")
        self.canvas = tk.Canvas(
            self.root, width=display_size[0], height=display_size[1], cursor="crosshair"
        )
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.bind("<ButtonPress-1>", self._start)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish)
        buttons = tk.Frame(self.root)
        buttons.pack(fill="x")
        tk.Button(buttons, text="Undo last ROI", command=self._undo).pack(side="left")
        tk.Button(buttons, text="Save ROIs", command=self._save).pack(side="right")
        self._update_instruction()

    def _update_instruction(self) -> None:
        if self.active_slot_index < len(self.slot_ids):
            slot = self.slot_ids[self.active_slot_index]
            self.instruction.set(
                f"Draw the parking-space ROI for slot {slot} by dragging. "
                f"{len(self.rectangles)}/{len(self.slot_ids)} selected."
            )
        else:
            self.instruction.set("All ROIs selected. Review the overlay and save.")

    def _start(self, event: object) -> None:
        if self.active_slot_index >= len(self.slot_ids):
            return
        self.drag_start = (event.x, event.y)
        if self.preview_rect is not None:
            self.canvas.delete(self.preview_rect)
        self.preview_rect = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#ff302e", width=2
        )

    def _drag(self, event: object) -> None:
        if self.drag_start is not None and self.preview_rect is not None:
            self.canvas.coords(
                self.preview_rect,
                self.drag_start[0],
                self.drag_start[1],
                event.x,
                event.y,
            )

    def _finish(self, event: object) -> None:
        if self.drag_start is None:
            return
        x0, y0 = self.drag_start
        self.drag_start = None
        x = max(0, min(int(min(x0, event.x) / self.scale), self.source_image.width - 1))
        y = max(0, min(int(min(y0, event.y) / self.scale), self.source_image.height - 1))
        right = max(0, min(int(max(x0, event.x) / self.scale), self.source_image.width))
        bottom = max(0, min(int(max(y0, event.y) / self.scale), self.source_image.height))
        if right <= x or bottom <= y:
            if self.preview_rect is not None:
                self.canvas.delete(self.preview_rect)
                self.preview_rect = None
            self.messagebox.showwarning(
                "Invalid ROI", "Drag a rectangle with positive width and height."
            )
            return
        slot_id = self.slot_ids[self.active_slot_index]
        proposed = dict(self.rectangles)
        proposed[slot_id] = (x, y, right - x, bottom - y)
        try:
            build_roi_config(
                image_size=self.source_image.size,
                slot_ids=self.slot_ids[: len(proposed)],
                rectangles=proposed,
                heuristic=self.heuristic,
            )
        except ValueError as error:
            if self.preview_rect is not None:
                self.canvas.delete(self.preview_rect)
                self.preview_rect = None
            self.messagebox.showerror("Invalid ROI", str(error))
            return
        self.rectangles = proposed
        self.active_slot_index += 1
        self._draw_overlay()
        self._update_instruction()

    def _draw_overlay(self) -> None:
        self.canvas.delete("roi")
        for slot_id, (x, y, width, height) in self.rectangles.items():
            x1, y1 = x * self.scale, y * self.scale
            x2, y2 = (x + width) * self.scale, (y + height) * self.scale
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="#ff302e", width=2, tags="roi")
            self.canvas.create_text(
                x1 + 4, y1 + 4, anchor="nw", text=f"Slot {slot_id}", fill="#ff302e", tags="roi"
            )

    def _undo(self) -> None:
        if not self.rectangles:
            return
        self.rectangles.pop(self.slot_ids[len(self.rectangles) - 1])
        self.active_slot_index = len(self.rectangles)
        self._draw_overlay()
        self._update_instruction()

    def _save(self) -> None:
        if len(self.rectangles) != len(self.slot_ids):
            self.messagebox.showwarning(
                "ROIs missing", "Select one ROI for every configured parking slot."
            )
            return
        config = build_roi_config(
            image_size=self.source_image.size,
            slot_ids=self.slot_ids,
            rectangles=self.rectangles,
            heuristic=self.heuristic,
        )
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        annotated = self.source_image.copy()
        draw = ImageDraw.Draw(annotated)
        for slot_id, (x, y, width, height) in self.rectangles.items():
            draw.rectangle((x, y, x + width, y + height), outline="#ff302e", width=3)
            draw.text((x + 4, y + 4), f"Slot {slot_id}", fill="#ff302e")
        self.overlay_path.parent.mkdir(parents=True, exist_ok=True)
        annotated.save(self.overlay_path)
        self.messagebox.showinfo(
            "Calibration saved", f"Config: {self.output_path}\nOverlay: {self.overlay_path}"
        )
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--camera-url", default=os.getenv("SMART_PARKING_CAMERA_URL", DEFAULT_CAMERA_URL)
    )
    parser.add_argument("--image", type=Path, help="calibrate a previously captured real JPEG")
    parser.add_argument("--output", type=Path, default=Path("config/rois.json"))
    parser.add_argument("--overlay", type=Path, default=Path("data/parking_roi_overlay.png"))
    parser.add_argument("--parking-config", type=Path, default=Path("config/parking.yaml"))
    parser.add_argument("--heuristic-config", type=Path, default=Path("config/rois.example.json"))
    args = parser.parse_args(argv)
    try:
        if args.image:
            with Image.open(args.image) as loaded:
                if loaded.format != "JPEG":
                    raise ValueError("input image must be a JPEG")
                image = loaded.convert("RGB")
        else:
            image = capture_jpeg(args.camera_url)
        parking = yaml.safe_load(args.parking_config.read_text(encoding="utf-8"))
        slot_ids = tuple(int(slot["id"]) for slot in parking["slots"])
        heuristic = json.loads(args.heuristic_config.read_text(encoding="utf-8"))["heuristic"]
        RoiCalibrationWindow(image, slot_ids, heuristic, args.output, args.overlay).run()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ROI calibration failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
