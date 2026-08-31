import unreal
import socket
import threading
import json
import queue
import traceback
import io
import contextlib

HOST = "127.0.0.1"
PORT = 6766
REQUEST_TIMEOUT_SECONDS = 180

request_queue = queue.Queue()
_running = True
_server_socket = None


def structured_execution_error(exc, *, code="PYTHON_EXECUTION_FAILED", recoverable=False, stdout=""):
    tb = traceback.format_exc()
    return {
        "ok": False,
        "code": code,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "error": tb,
        "traceback": tb,
        "recoverable": bool(recoverable),
        "stdout": stdout,
    }


class BridgeRequest:
    def __init__(self, payload):
        self.payload = payload
        self.result = None
        self.done = threading.Event()


def json_safe(value):
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def process_request(payload):
    request_type = payload.get("type")

    if request_type == "ping":
        return {
            "ok": True,
            "message": "UNREAL_BRIDGE_READY",
            "engine": unreal.SystemLibrary.get_engine_version()
        }

    if request_type == "python":
        code = payload.get("code", "")

        namespace = {
            "__builtins__": __builtins__,
            "unreal": unreal,
            "json": json,
            "__bridge_result__": None
        }

        stdout = io.StringIO()

        try:
            with contextlib.redirect_stdout(stdout):
                exec(code, namespace, namespace)

            return {
                "ok": True,
                "message": "Python executed on Unreal main thread",
                "result": json_safe(namespace.get("__bridge_result__")),
                "stdout": stdout.getvalue()
            }

        except Exception as exc:
            is_compile = "compile_blueprint" in str(code)
            return structured_execution_error(
                exc,
                code="BLUEPRINT_COMPILE_FAILED" if is_compile else "PYTHON_EXECUTION_FAILED",
                recoverable=is_compile,
                stdout=stdout.getvalue(),
            )

    return {
        "ok": False,
        "error": f"Unknown request type: {request_type}"
    }


def on_editor_tick(delta_seconds):
    processed = 0

    while processed < 10:
        try:
            request = request_queue.get_nowait()
        except queue.Empty:
            break

        try:
            request.result = process_request(request.payload)
        except Exception as exc:
            request.result = structured_execution_error(exc)

        request.done.set()
        processed += 1


def handle_client(conn):
    try:
        data = b""

        while b"\n" not in data:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk

        if not data:
            return

        payload = json.loads(data.decode("utf-8").strip())

        request = BridgeRequest(payload)
        request_queue.put(request)

        if not request.done.wait(timeout=REQUEST_TIMEOUT_SECONDS):
            response = {
                "ok": False,
                "error": "Unreal main-thread request timed out"
            }
        else:
            response = request.result

        conn.sendall(
            (json.dumps(response) + "\n").encode("utf-8")
        )

    except Exception as exc:
        try:
            conn.sendall(
                (json.dumps(structured_execution_error(exc, code="BRIDGE_REQUEST_FAILED")) + "\n").encode("utf-8")
            )
        except Exception:
            pass

    finally:
        conn.close()


def server_loop():
    global _server_socket

    _server_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    _server_socket.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    _server_socket.bind((HOST, PORT))
    _server_socket.listen(5)

    unreal.log(
        f"Unreal Agent Bridge listening on {HOST}:{PORT}"
    )

    while _running:
        try:
            conn, addr = _server_socket.accept()

            threading.Thread(
                target=handle_client,
                args=(conn,),
                daemon=True
            ).start()

        except Exception as exc:
            if _running:
                print(exc)


_tick_handle = unreal.register_slate_post_tick_callback(
    on_editor_tick
)

threading.Thread(
    target=server_loop,
    daemon=True
).start()

unreal.log("UNREAL AGENT BRIDGE STARTED - RESULT MODE")
