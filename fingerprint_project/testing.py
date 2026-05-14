"""
Fingerprint Pipeline Testing Tool
──────────────────────────────────
Simulates sending an image through the fingerprint matching pipeline
to diagnose matching issues. Supports:
  - Camera photos (thumb or paper fingerprint)
  - Raw AS608 sensor binary data
  - Step-by-step image saving for visual debugging
  - Self-test mode (match an enrolled image against itself)

Usage:
    python testing.py <image_path>                     # Basic test
    python testing.py <image_path> --student 15        # Match against specific student
    python testing.py <image_path> --pipeline sensor   # Use sensor pipeline
    python testing.py <image_path> --save-steps        # Save every intermediate image
    python testing.py --self-test                       # Self-match sanity check
"""

import os
import django
import cv2
import numpy as np
from PIL import Image
import io
import argparse
from pathlib import Path
import logging

# 1. Initialize Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fingerprint_project.settings')
django.setup()

from fingerprint.models import Student
from fingerprint.preprocessing.pipeline import preprocess_camera_image, preprocess_sensor_image
from fingerprint.preprocessing.region_detector import detect_and_crop_fingerprint
from fingerprint.templates_engine.matcher import match_fingerprints
from fingerprint.templates_engine.extractor import extract_template
from fingerprint.views import _parse_sensor_image

# Configure logging to see pipeline steps
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('fingerprint_test')

# Directory for test results
TEST_RESULT_DIR = Path('captured_fingerprints/test_results')
TEST_RESULT_DIR.mkdir(parents=True, exist_ok=True)


def _save_step(image, step_name, tag):
    """Save an intermediate pipeline image for visual inspection."""
    path = TEST_RESULT_DIR / f"{tag}_{step_name}.png"
    if len(image.shape) == 3:
        cv2.imwrite(str(path), image)
    else:
        cv2.imwrite(str(path), image)
    print(f"    [step] {step_name}: saved to {path} (shape={image.shape})")
    return path


def run_test(image_path, student_id=None, is_raw_sensor=False, pipeline_mode='camera', save_steps=False):
    """
    Test the fingerprint matching pipeline.

    Args:
        image_path: Path to the image file (PNG, JPG or raw BIN)
        student_id: Optional student ID to match against specifically
        is_raw_sensor: If True, treats the file as raw AS608 binary data (36864 bytes)
        pipeline_mode: 'camera' or 'sensor'
        save_steps: If True, saves every intermediate preprocessing image
    """
    tag = Path(image_path).stem
    print(f"\n{'='*70}")
    print(f"  FINGERPRINT PIPELINE TEST (Minutiae Extraction)")
    print(f"  Image:    {image_path}")
    print(f"  Pipeline: {pipeline_mode}")
    print(f"  Steps:    {'saving all intermediates' if save_steps else 'final only'}")
    print(f"{'='*70}")

    # ── 1. Load/Parse Image ──
    if is_raw_sensor:
        print(f"\n[1/4] Parsing as raw AS608 sensor data...")
        with open(image_path, 'rb') as f:
            image_bytes = f.read()
        print(f"      Raw data size: {len(image_bytes)} bytes")
        pil_image = _parse_sensor_image(image_bytes)
    else:
        print(f"\n[1/4] Loading image file...")
        pil_image = Image.open(image_path)

    print(f"      Image size: {pil_image.size}, mode: {pil_image.mode}")

    # Save original for reference
    original_path = TEST_RESULT_DIR / f"{tag}_00_original.png"
    pil_image.save(original_path)
    print(f"      Saved original to: {original_path}")

    # ── 2. Preprocess ──
    print(f"\n[2/4] Running preprocessing ({pipeline_mode} pipeline)...")

    if pipeline_mode == 'sensor':
        img_array = np.array(pil_image.convert('L'))
        result = preprocess_sensor_image(img_array)
    else:
        img_array = np.array(pil_image.convert('RGB'))
        result = preprocess_camera_image(img_array)

    processed_image = result.processed_image
    minutiae_data = result.minutiae_data

    print(f"      Quality Score: {result.quality_result.overall_score:.2f}")
    print(f"      Steps: {', '.join(result.steps_completed)}")

    if minutiae_data:
        minutiae_count = len(minutiae_data.get('minutiae_points', []))
        sing_count = len(minutiae_data.get('singularities_points', []))
        print(f"      Minutiae found: {minutiae_count}")
        print(f"      Singularities found: {sing_count}")

        # Count minutiae by type
        endings = sum(1 for m in minutiae_data['minutiae_points'] if m['type'] == 'ending')
        bifurcations = sum(1 for m in minutiae_data['minutiae_points'] if m['type'] == 'bifurcation')
        print(f"        - Ridge endings: {endings}")
        print(f"        - Bifurcations: {bifurcations}")

        # Count singularities by type
        for stype in ['loop', 'delta', 'whorl']:
            count = sum(1 for s in minutiae_data['singularities_points'] if s['type'] == stype)
            if count > 0:
                print(f"        - {stype.title()}s: {count}")

    if save_steps and minutiae_data:
        _save_pipeline_steps(minutiae_data, processed_image, tag)

    # Save processed result
    processed_path = TEST_RESULT_DIR / f"{tag}_final_processed.png"
    cv2.imwrite(str(processed_path), processed_image)
    print(f"      Final processed image: {processed_path}")

    # ── 3. Match ──
    print(f"\n[3/4] Matching against database...")

    if student_id:
        students = Student.objects.filter(student_id=student_id)
        if not students.exists():
            print(f"      [!] Error: Student with ID {student_id} not found.")
            return
        print(f"      Matching against student {student_id} only")
    else:
        students = Student.objects.exclude(fingerprint_image__isnull=True)
        print(f"      Matching against {students.count()} enrolled students...")

    results = []
    for student in students:
        if not student.fingerprint_image:
            continue

        try:
            stored_image = np.frombuffer(
                bytes(student.fingerprint_image), dtype=np.uint8
            ).reshape((512, 512))

            match_res = match_fingerprints(
                processed_image, stored_image, method='combined',
                minutiae_data1=minutiae_data,
            )

            results.append({
                'id': student.student_id,
                'name': student.full_name,
                'reg': student.registration_no,
                'score': match_res.score,
                'is_match': match_res.is_match,
                'interpretation': match_res.interpretation
            })
        except Exception as e:
            print(f"      [!] Error matching student {student.student_id}: {e}")

    # ── 4. Report ──
    results.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n[4/4] Results")
    print('-'*70)
    print(f"  {'STUDENT':<35} {'SCORE':>8}  {'STATUS':<20}")
    print('-'*70)

    for r in results[:10]:
        marker = " MATCH" if r['is_match'] else ""
        print(f"  {r['name']} ({r['reg']})".ljust(37) + f"{r['score']:>6.2f}  {r['interpretation']}{marker}")

    print('-'*70)

    if not results:
        print("  [!] No students with fingerprint images found in database.")
    elif not any(r['is_match'] for r in results):
        print(f"  [!] NO MATCH. Best score: {results[0]['score']:.2f} (threshold: 30)")
    else:
        best = results[0]
        print(f"  [OK] MATCHED: {best['name']} (score={best['score']:.2f})")

    print()


def _save_pipeline_steps(minutiae_data, processed_image, tag):
    """Save all intermediate pipeline images for visual debugging."""
    step_images = {
        '01_resized': processed_image,
        '02_normalized': minutiae_data.get('normalized_img'),
        '03_segmented': minutiae_data.get('segmented_img'),
        '04_orientation': minutiae_data.get('orientation_img'),
        '05_gabor': minutiae_data.get('gabor_img'),
        '06_skeleton': minutiae_data.get('thin_image'),
        '07_minutiae': minutiae_data.get('minutias_img'),
        '08_singularities': minutiae_data.get('singularities_img'),
    }

    for step_name, img in step_images.items():
        if img is not None:
            _save_step(img, step_name, tag)


def run_self_test():
    """
    Self-test: take the first enrolled student's stored fingerprint image,
    run it back through the pipeline, and match it against itself.
    Should produce a high score (ideally 60+) if the pipeline is working.
    """
    print(f"\n{'='*70}")
    print(f"  SELF-TEST: Matching enrolled image against itself")
    print(f"{'='*70}")

    students = Student.objects.exclude(fingerprint_image__isnull=True)
    if not students.exists():
        print("  [!] No enrolled students with fingerprint images found.")
        return

    for student in students[:3]:  # Test first 3 students
        try:
            stored_image = np.frombuffer(
                bytes(student.fingerprint_image), dtype=np.uint8
            ).reshape((512, 512))

            # Match the stored image directly against itself (no re-preprocessing)
            result = match_fingerprints(stored_image, stored_image, method='combined')

            status = "PASS" if result.score > 50 else "FAIL (pipeline issue)"
            print(f"\n  Student: {student.full_name} (ID={student.student_id})")
            print(f"  Self-match score: {result.score:.2f} — {status}")

            # Also test: save the stored image, reload it, preprocess, and match
            temp_path = TEST_RESULT_DIR / f"selftest_stored_{student.student_id}.png"
            cv2.imwrite(str(temp_path), stored_image)

            reloaded = cv2.imread(str(temp_path), cv2.IMREAD_GRAYSCALE)
            re_result = preprocess_camera_image(
                cv2.cvtColor(reloaded, cv2.COLOR_GRAY2RGB)
            )
            round_trip = match_fingerprints(
                re_result.processed_image, stored_image, method='combined',
                minutiae_data1=re_result.minutiae_data,
            )

            status2 = "PASS" if round_trip.score > 30 else "FAIL"
            print(f"  Round-trip score (save > reload > preprocess > match): {round_trip.score:.2f} -- {status2}")

        except Exception as e:
            print(f"  [!] Error testing student {student.student_id}: {e}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test fingerprint matching pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python testing.py photo.jpg                          # Test a camera photo
  python testing.py paper_print.png --save-steps       # Test paper fingerprint with debug images
  python testing.py sensor.bin --raw --pipeline sensor  # Test raw sensor data
  python testing.py --self-test                         # Sanity check the pipeline
        """
    )
    parser.add_argument("image", nargs='?', help="Path to test fingerprint image")
    parser.add_argument("--student", type=int, help="Specific student ID to match against")
    parser.add_argument("--raw", action="store_true", help="Treat input as raw AS608 binary data")
    parser.add_argument("--pipeline", choices=['camera', 'sensor'], default='camera',
                        help="Preprocessing pipeline to use (default: camera)")
    parser.add_argument("--save-steps", action="store_true",
                        help="Save every intermediate preprocessing image for debugging")
    parser.add_argument("--self-test", action="store_true",
                        help="Run self-match test (enrolled image vs itself)")

    args = parser.parse_args()

    try:
        if args.self_test:
            run_self_test()
        elif args.image:
            run_test(args.image, args.student, args.raw, args.pipeline, args.save_steps)
        else:
            parser.print_help()
    except Exception as e:
        print(f"\n[CRITICAL ERROR] {e}")
        import traceback
        traceback.print_exc()
