import webbrowser

import uvicorn


def main() -> None:
    url = "http://127.0.0.1:8765"
    webbrowser.open(url)
    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
