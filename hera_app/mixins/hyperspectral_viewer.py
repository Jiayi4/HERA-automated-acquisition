import math


class HyperspectralViewerMixin:
    def _clear_hypercube_viewer(self):
        if self.current_hypercube_handle and self.controller:
            if self.current_hypercube_handle != self.flatfield_hypercube_handle:
                try:
                    self.controller.release_hypercube(self.current_hypercube_handle)
                except Exception:
                    pass
        self.current_hypercube_handle = None
        self.current_hypercube_info = None
        self.current_hyper_band_cache = {}
        self.current_hyper_spectrum_cache = {}
        self.hyper_selected_pixel = None
        self.hyper_display_rect = None
        self.current_hyper_band_index.set(0)
        self.current_hyper_band_var.set("Band: -")
        self.current_hyper_wavelength_var.set("Wavelength: -")
        self.hypercube_summary_var.set("Cube: waiting for acquisition")
        self.acquisition_requested_roi = None
        self.hyper_photo = None
        if hasattr(self, "hyper_band_scale"):
            self.hyper_band_scale.config(to=0)
        self._safe_after(0, self.render_current_hyper_band)

    def on_hyper_band_changed(self, _value=None):
        self.render_current_hyper_band()

    def step_hyper_band(self, delta):
        if not self.current_hypercube_info:
            self.log("Run an acquisition first so the hyperspectral viewer has bands to browse.")
            return
        max_band_index = max(self.current_hypercube_info["bands"] - 1, 0)
        next_index = min(max(int(self.current_hyper_band_index.get()) + delta, 0), max_band_index)
        self.current_hyper_band_index.set(next_index)
        self.hyper_band_jump_var.set(str(next_index + 1))
        self.render_current_hyper_band()

    def jump_to_hyper_band(self):
        if not self.current_hypercube_info:
            self.log("Run an acquisition first so the hyperspectral viewer has bands to browse.")
            return
        try:
            requested_band = int(self.hyper_band_jump_var.get().strip())
        except ValueError:
            self.log("Enter a whole-number band index to jump.")
            return
        max_band = self.current_hypercube_info["bands"]
        clamped_band = min(max(requested_band, 1), max_band)
        self.current_hyper_band_index.set(clamped_band - 1)
        self.hyper_band_jump_var.set(str(clamped_band))
        self.render_current_hyper_band()

    def on_hyper_mousewheel(self, event):
        if getattr(event, "delta", 0) > 0:
            self.step_hyper_band(1)
        elif getattr(event, "delta", 0) < 0:
            self.step_hyper_band(-1)

    def _crop_hyper_band_values_for_display(self, band_values, source_width, display_roi):
        if not display_roi:
            return band_values
        roi_x, roi_y, roi_w, roi_h = display_roi
        cropped = []
        for row in range(roi_y, roi_y + roi_h):
            start = row * source_width + roi_x
            cropped.extend(band_values[start:start + roi_w])
        return cropped

    def _get_hyper_band_values_for_display(self, band_index):
        source_width = self.current_hypercube_info.get("source_width", self.current_hypercube_info["width"])
        source_height = self.current_hypercube_info.get("source_height", self.current_hypercube_info["height"])
        display_roi = self.current_hypercube_info.get("display_roi")
        wavelength, band_values = self.controller.get_hypercube_band_data(
            self.current_hypercube_handle,
            band_index,
            source_width,
            source_height,
            self.current_hypercube_info["data_type"],
        )
        band_values = self._crop_hyper_band_values_for_display(band_values, source_width, display_roi)
        if (
            self.current_hypercube_info.get("role") != "flatfield"
            and self._should_use_flatfield_correction(self.current_hypercube_info)
        ):
            _, flat_values = self.controller.get_hypercube_band_data(
                self.flatfield_hypercube_handle,
                band_index,
                source_width,
                source_height,
                self.current_hypercube_info["data_type"],
            )
            flat_values = self._crop_hyper_band_values_for_display(flat_values, source_width, display_roi)
            band_values = [
                float(sample) / float(flat) if abs(float(flat)) > 1e-12 else 0.0
                for sample, flat in zip(band_values, flat_values)
            ]
        return wavelength, band_values

    def _event_to_hyper_image_xy(self, event):
        rect = self.hyper_display_rect
        if not rect or not self.current_hypercube_info:
            return None
        left, top, out_w, out_h = rect
        if event.x < left or event.x >= left + out_w or event.y < top or event.y >= top + out_h:
            return None
        frame_width = self.current_hypercube_info["width"]
        frame_height = self.current_hypercube_info["height"]
        image_x = min(max(int((event.x - left) * frame_width / out_w), 0), frame_width - 1)
        image_y = min(max(int((event.y - top) * frame_height / out_h), 0), frame_height - 1)
        return image_x, image_y

    def on_hyper_mouse_click(self, event):
        image_pos = self._event_to_hyper_image_xy(event)
        if not image_pos:
            return
        self.hyper_selected_pixel = image_pos
        self.current_hyper_spectrum_cache = {}
        self._draw_hyper_spectrum_panel()
        self.render_current_hyper_band()

    def _get_hyper_pixel_spectrum(self, image_x, image_y):
        cache_key = (image_x, image_y, bool(self.use_flatfield_var.get()))
        width = self.current_hypercube_info["width"]
        index = image_y * width + image_x
        spectrum_by_band = self.current_hyper_spectrum_cache.setdefault(cache_key, {})
        for band_index, cached_band in self.current_hyper_band_cache.items():
            if len(cached_band) < 3:
                continue
            wavelength, _, band_values = cached_band
            if 0 <= index < len(band_values):
                spectrum_by_band[band_index] = (wavelength, float(band_values[index]))
        return [spectrum_by_band[key] for key in sorted(spectrum_by_band)]

    def _draw_hyper_spectrum_panel(self):
        if not hasattr(self, "hyper_spectrum_canvas"):
            return
        canvas = self.hyper_spectrum_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 10)
        height = max(canvas.winfo_height(), 10)
        pad_left, pad_right, pad_top, pad_bottom = 48, 14, 18, 28
        canvas.create_rectangle(0, 0, width, height, fill=self.theme["canvas"], outline="")
        plot_w = max(width - pad_left - pad_right, 1)
        plot_h = max(height - pad_top - pad_bottom, 1)
        x0, y0 = pad_left, pad_top
        x1, y1 = pad_left + plot_w, pad_top + plot_h
        for i in range(5):
            y = y0 + i * plot_h / 4
            canvas.create_line(x0, y, x1, y, fill=self.theme["canvas_grid"])
        canvas.create_line(x0, y0, x0, y1, fill=self.theme["muted"])
        canvas.create_line(x0, y1, x1, y1, fill=self.theme["muted"])
        canvas.create_text(8, 8, anchor="nw", text="Spectrum panel", fill=self.theme["muted"], font=("Segoe UI", 8))
        if not self.current_hypercube_info or not self.hyper_selected_pixel:
            canvas.create_text(width / 2, height / 2, text="Click the hyperspectral image to plot a pixel spectrum", fill=self.theme["muted"], font=("Segoe UI", 9))
            return
        try:
            image_x, image_y = self.hyper_selected_pixel
            spectrum = self._get_hyper_pixel_spectrum(image_x, image_y)
        except Exception as exc:
            canvas.create_text(width / 2, height / 2, text=f"Spectrum unavailable: {exc}", fill=self.theme["muted"], font=("Segoe UI", 9))
            return
        if len(spectrum) < 2:
            canvas.create_text(width / 2, height / 2, text="Move through bands to build the spectrum", fill=self.theme["muted"], font=("Segoe UI", 9))
            return
        wavelengths = [point[0] for point in spectrum]
        values = [point[1] for point in spectrum]
        min_w, max_w = min(wavelengths), max(wavelengths)
        min_v, max_v = min(values), max(values)
        if math.isclose(min_v, max_v):
            min_v -= 1.0
            max_v += 1.0
        current_band = min(max(int(self.current_hyper_band_index.get()), 0), len(spectrum) - 1)
        current_w = wavelengths[current_band]
        current_x = x0 + ((current_w - min_w) / max(max_w - min_w, 1e-12)) * plot_w
        canvas.create_line(current_x, y0, current_x, y1, fill="#ff8b3d", width=1)
        prev = None
        for wavelength, value in spectrum:
            x = x0 + ((wavelength - min_w) / max(max_w - min_w, 1e-12)) * plot_w
            y = y1 - ((value - min_v) / max(max_v - min_v, 1e-12)) * plot_h
            if prev:
                canvas.create_line(prev[0], prev[1], x, y, fill=self.theme["accent_soft"], width=2)
            prev = (x, y)
        canvas.create_text(x0, height - 8, anchor="sw", text=f"{min_w:.0f}", fill=self.theme["muted"], font=("Segoe UI", 8))
        canvas.create_text(x1, height - 8, anchor="se", text=f"{max_w:.0f}", fill=self.theme["muted"], font=("Segoe UI", 8))
        canvas.create_text(width - 10, 8, anchor="ne", text=f"Pixel selection X={image_x} Y={image_y}", fill=self.theme["text"], font=("Segoe UI", 9))

    def render_current_hyper_band(self):
        if not hasattr(self, "hyper_view_canvas"):
            return
        if not self.current_hypercube_info or not self.current_hypercube_handle or not self.controller:
            self._draw_hyperspectral_view_placeholder()
            return
        try:
            band_index = min(max(int(self.current_hyper_band_index.get()), 0), self.current_hypercube_info["bands"] - 1)
            self.current_hyper_band_index.set(band_index)
            if band_index not in self.current_hyper_band_cache:
                wavelength, band_values = self._get_hyper_band_values_for_display(band_index)
                min_value = min(band_values)
                max_value = max(band_values)
                if math.isclose(min_value, max_value):
                    gray_bytes = bytes([0] * len(band_values))
                else:
                    scale = 255.0 / (max_value - min_value)
                    gray_bytes = bytes(
                        max(0, min(255, int((value - min_value) * scale)))
                        for value in band_values
                    )
                self.current_hyper_band_cache[band_index] = (wavelength, gray_bytes, band_values)
                self.log(
                    f"Hyperspectral band {band_index + 1}/{self.current_hypercube_info['bands']} "
                    f"render range: min={min_value:.6f}, max={max_value:.6f}, wavelength={wavelength:.3f}"
                )
            wavelength, gray_bytes = self.current_hyper_band_cache[band_index][:2]
            canvas = self.hyper_view_canvas
            canvas.delete("all")
            width = max(canvas.winfo_width(), 10)
            height = max(canvas.winfo_height(), 10)
            self.hyper_photo, out_w, out_h = self._make_ppm_photo_from_grayscale(
                gray_bytes,
                self.current_hypercube_info["width"],
                self.current_hypercube_info["height"],
                max(width - 16, 1),
                max(height - 16, 1),
            )
            left = (width - out_w) / 2
            top = (height - out_h) / 2
            self.hyper_display_rect = (left, top, out_w, out_h)
            canvas.create_rectangle(0, 0, width, height, fill=self.theme["canvas"], outline="")
            canvas.create_image(width / 2, height / 2, image=self.hyper_photo, anchor="center")
            if self.hyper_selected_pixel:
                sx, sy = self.hyper_selected_pixel
                if sx >= self.current_hypercube_info["width"] or sy >= self.current_hypercube_info["height"]:
                    self.hyper_selected_pixel = None
                else:
                    cache_key = (sx, sy, bool(self.use_flatfield_var.get()))
                    index = sy * self.current_hypercube_info["width"] + sx
                    if len(self.current_hyper_band_cache[band_index]) >= 3:
                        _, _, band_values = self.current_hyper_band_cache[band_index]
                        if 0 <= index < len(band_values):
                            self.current_hyper_spectrum_cache.setdefault(cache_key, {})[band_index] = (wavelength, float(band_values[index]))
            if self.hyper_selected_pixel:
                sx, sy = self.hyper_selected_pixel
                marker_x = left + (sx + 0.5) * out_w / self.current_hypercube_info["width"]
                marker_y = top + (sy + 0.5) * out_h / self.current_hypercube_info["height"]
                canvas.create_line(marker_x - 9, marker_y, marker_x + 9, marker_y, fill="#ffd15c", width=2)
                canvas.create_line(marker_x, marker_y - 9, marker_x, marker_y + 9, fill="#ffd15c", width=2)
                canvas.create_oval(marker_x - 4, marker_y - 4, marker_x + 4, marker_y + 4, outline="#ffd15c", width=2)
            canvas.create_text(
                12,
                12,
                anchor="nw",
                text=f"{self.current_hypercube_info['width']} x {self.current_hypercube_info['height']}",
                fill=self.theme["text"],
                font=("Segoe UI", 9),
            )
            self.current_hyper_band_var.set(f"Band: {band_index + 1} / {self.current_hypercube_info['bands']}")
            self.hyper_band_jump_var.set(str(band_index + 1))
            self.current_hyper_wavelength_var.set(f"Wavelength: {wavelength:.3f}")
            self._draw_hyper_spectrum_panel()
        except Exception as exc:
            self.log(f"Failed to render hyperspectral band: {exc}")
            self._draw_hyperspectral_view_placeholder()

    def _draw_hyperspectral_view_placeholder(self):
        if not hasattr(self, "hyper_view_canvas"):
            return
        self.hyper_display_rect = None
        canvas = self.hyper_view_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 10)
        height = max(canvas.winfo_height(), 10)
        canvas.create_rectangle(0, 0, width, height, fill=self.theme["canvas"], outline="")
        for i, color in enumerate(["#24435b", "#2f6c8f", "#4ea4cf", "#7fd0ff", "#ff8b3d"]):
            x0 = 18 + i * 30
            canvas.create_rectangle(x0, height - 42, x0 + 20, height - 18, fill=color, outline="")
        if self.app_state in {self.STATE_LABELS["Acquiring"], self.STATE_LABELS["WaitingForTrigger"], self.STATE_LABELS["ComputingHypercube"], self.STATE_LABELS["Saving"]}:
            detail_text = "Waiting for the current acquisition and cube computation to finish"
        else:
            detail_text = "Run one acquisition to populate the in-app band viewer"
        canvas.create_text(width / 2, height / 2 - 20, text="Hyperspectral View", fill=self.theme["text"], font=("Segoe UI Semibold", 14))
        canvas.create_text(width / 2, height / 2 + 2, text=detail_text, fill=self.theme["muted"], font=("Segoe UI", 10))
        export_text = self.last_export_var.get() if hasattr(self, "last_export_var") else "Last export: -"
        canvas.create_text(width / 2, height / 2 + 24, text=self.hypercube_summary_var.get(), fill=self.theme["text"], font=("Segoe UI", 10))
        canvas.create_text(width / 2, height / 2 + 46, text=export_text, fill=self.theme["muted"], font=("Segoe UI", 10))
        self._draw_hyper_spectrum_panel()
