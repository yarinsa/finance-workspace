"""Generate a VAPID key pair for Web Push and print the .env lines.

  poetry run python sync/push_keys.py you@example.com

Prints, never writes: paste the three lines into the repo-root .env on the Mac. The private
key stays there; docker compose gives the API container only PUSH_VAPID_PUBLIC_KEY.
Re-generating invalidates every existing subscription (turn notifications off and on in the app).
"""
import base64
import sys

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    """(private, public) as unpadded base64url: the raw 32-byte scalar and the 65-byte point."""
    v = Vapid()
    v.generate_keys()
    private = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    public = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64(private), b64(public)


def main(argv) -> int:
    if len(argv) != 2 or "@" not in argv[1]:
        print(__doc__)
        return 2
    private, public = generate()
    print(f"PUSH_VAPID_PRIVATE_KEY={private}")
    print(f"PUSH_VAPID_PUBLIC_KEY={public}")
    print(f"PUSH_VAPID_SUBJECT=mailto:{argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
