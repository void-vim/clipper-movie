{ pkgs ? import <nixpkgs> {} }:

# Chatterbox needs real wheels (torch etc.), so python deps come from uv while
# espeak-ng/ffmpeg/zlib come from nix for runtime library resolution.
pkgs.mkShell {
  name = "clipper-movie";
  buildInputs = [
    pkgs.uv
    pkgs.python312
    pkgs.stdenv.cc.cc.lib
    pkgs.zlib
    pkgs.portaudio
    pkgs.espeak-ng
    pkgs.ffmpeg
  ];
  shellHook = ''
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib:${pkgs.portaudio}/lib:$LD_LIBRARY_PATH"

    expected_venv="$(pwd)/.venv"
    if [ ! -d .venv ] || [ "$(grep -o "VIRTUAL_ENV='[^']*'" .venv/bin/activate | cut -d\' -f2)" != "$expected_venv" ]; then
      rm -rf .venv
      uv venv --python ${pkgs.python312}/bin/python .venv
    fi
    source .venv/bin/activate

    uv pip install --python .venv/bin/python \
      chatterbox-tts soundfile torchaudio torch huggingface_hub perth

    # Pre-fetch Chatterbox weights into the HF cache (cached; fast on re-entry)
    python3 -c "from huggingface_hub import snapshot_download; snapshot_download('ResembleAI/chatterbox')" || true

    echo "[INFO] run: python main.py --video movie.mp4 --subtitle movie.srt"
  '';
}
