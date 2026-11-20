#!/bin/sh
# Build the submission zip: transmitter, receiver and experiment code only.
# Leaves out data, figures, tables, notes, plotting scripts and archive/.
#     sh make_submission.sh
# Writes ../submission/COMP0228_CW1_GRP1/ and ../COMP0228_CW1_GRP1.zip
set -e
cd "$(dirname "$0")"

NAME=COMP0228_CW1_GRP1
OUT=../submission
STAGE=$OUT/$NAME

FILES="
piezo_receiver_v3/piezo_receiver_v3.ino
channel/hardware.py
channel/sim_channel.py
codes/__init__.py
codes/repetition.py
codes/hamming.py
codes/convolutional.py
codes/filtering.py
codes/cnn_decoder.py
experiments/run_case.py
experiments/sequences.py
experiments/extensions.py
experiments/filter_bands.json
experiments/summarise.py
experiments/live_view.py
experiments/scope.py
experiments/make_video.py
models/cnn_decoder.pt
models/cnn_decoder_linear.pt
run_sim.py
requirements.txt
"

rm -rf "$STAGE" "../$NAME.zip"
mkdir -p "$STAGE"
for f in $FILES; do
    [ -f "$f" ] || { echo "Missing: $f" >&2; exit 1; }
    mkdir -p "$STAGE/$(dirname "$f")"
    cp "$f" "$STAGE/$f"
done
cp SUBMISSION_README.md "$STAGE/README.md"

(cd "$OUT" && zip -qr "../$NAME.zip" "$NAME" -x '*.DS_Store' '*__pycache__*')
echo "Staged in $STAGE"
echo "Zipped to ../$NAME.zip"
