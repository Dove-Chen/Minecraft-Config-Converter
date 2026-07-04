LEGAL_ELEMENT_ROTATION_ANGLES = (-45.0, -22.5, 0.0, 22.5, 45.0)


def _nearest_legal_element_angle(angle):
    return min(LEGAL_ELEMENT_ROTATION_ANGLES, key=lambda allowed: abs(angle - allowed))


def _format_element_angle(angle):
    return int(angle) if float(angle).is_integer() else angle


def normalize_illegal_element_rotations(model_data):
    """Clamp Java model element rotations to the nearest allowed angle."""
    elements = model_data.get("elements") if isinstance(model_data, dict) else None
    if not isinstance(elements, list):
        return 0

    changed = 0
    for element in elements:
        if not isinstance(element, dict):
            continue
        rotation = element.get("rotation")
        if not isinstance(rotation, dict) or "angle" not in rotation:
            continue
        try:
            angle = float(rotation["angle"])
        except (TypeError, ValueError):
            continue
        if angle in LEGAL_ELEMENT_ROTATION_ANGLES:
            continue
        replacement = _nearest_legal_element_angle(angle)
        rotation["angle"] = _format_element_angle(replacement)
        changed += 1

    return changed


def normalize_blockbench_euler_element_rotations(model_data):
    """Convert Blockbench x/y/z element rotations into Java model axis/angle rotations."""
    elements = model_data.get("elements") if isinstance(model_data, dict) else None
    if not isinstance(elements, list):
        return 0

    changed = 0
    for element in elements:
        if not isinstance(element, dict):
            continue
        rotation = element.get("rotation")
        if not isinstance(rotation, dict) or "angle" in rotation:
            continue

        components = []
        for axis in ("x", "y", "z"):
            try:
                value = float(rotation.get(axis, 0) or 0)
            except (TypeError, ValueError):
                value = 0.0
            components.append((axis, value))

        axis, raw_angle = max(components, key=lambda item: abs(item[1]))
        replacement = _nearest_legal_element_angle(raw_angle)
        converted = {
            "angle": _format_element_angle(replacement),
            "axis": axis,
        }
        if "origin" in rotation:
            converted["origin"] = rotation["origin"]
        if "rescale" in rotation:
            converted["rescale"] = rotation["rescale"]

        element["rotation"] = converted
        changed += 1

    return changed
