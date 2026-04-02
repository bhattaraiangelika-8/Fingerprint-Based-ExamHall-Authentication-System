import sys
from fingerprint import FingerprintModule, CaptureFingerImage, get_port_from_user


def extract_image(output_path="fingerprint.png"):
    port = get_port_from_user()
    module = FingerprintModule(port)

    if not module.connect():
        print("Could not connect.")
        return False

    input("Press enter to scan finger.")
    result = module.capture_finger_image()
    if result != CaptureFingerImage.SUCCESS:
        print("Could not capture finger image.")
        module.disconnect()
        return False

    print("Transferring bytes...")
    data = module.read_image_buffer()
    if not data:
        print("Could not read image buffer.")
        module.disconnect()
        return False

    module.disconnect()

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is required. Install with: pip install matplotlib")
        return False

    image = FingerprintModule.decode_image_buffer(data)
    plt.imsave(output_path, image, cmap='gray')
    print(f"Image saved to {output_path}")
    return True


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "fingerprint.png"
    extract_image(output)
