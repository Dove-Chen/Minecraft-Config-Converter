LEGAL_ELEMENT_ROTATION_ANGLES = (-45.0, -22.5, 0.0, 22.5, 45.0)


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
        replacement = min(LEGAL_ELEMENT_ROTATION_ANGLES, key=lambda allowed: abs(angle - allowed))
        rotation["angle"] = int(replacement) if replacement.is_integer() else replacement
        changed += 1

    return changed
