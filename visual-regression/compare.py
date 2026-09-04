from pathlib import Path
from PIL import Image, ImageChops, ImageStat
import sys

reference = Image.open(sys.argv[1]).convert("RGB")
current = Image.open(sys.argv[2]).convert("RGB")
if current.size != reference.size:
    current = current.resize(reference.size, Image.Resampling.LANCZOS)
diff = ImageChops.difference(reference, current)
stat = ImageStat.Stat(diff)
mae = sum(stat.mean) / 3
similarity = max(0.0, 100.0 * (1.0 - mae / 255.0))
diff.save(Path(sys.argv[2]).with_name("diff.png"))
print(f"reference={reference.size[0]}x{reference.size[1]}")
print(f"current={current.size[0]}x{current.size[1]}")
print(f"mean_absolute_error={mae:.3f}")
print(f"pixel_similarity={similarity:.2f}%")
