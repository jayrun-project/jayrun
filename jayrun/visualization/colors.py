"""Stable artifact identity palette; status never replaces these colors."""
import colorsys

_PALETTE = ("#38CDE0", "#AC8AFF", "#F3BE50", "#67D6A3", "#EF90BD", "#7CAEFF", "#EF7B73", "#BAD76D")


def artifact_color(index: int) -> str:
    if index < len(_PALETTE):
        return _PALETTE[index]
    rgb = colorsys.hls_to_rgb((0.57 + index * 0.618033988749895) % 1, 0.68, 0.65)
    return "#{:02X}{:02X}{:02X}".format(*(round(channel * 255) for channel in rgb))
