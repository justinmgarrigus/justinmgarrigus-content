#!/usr/bin/env bash
# Regenerates the starter GIFs in static/ with ImageMagick. These are only
# placeholders so the theme works out of the box; replace them with real
# finds (https://gifcities.org searches the GeoCities archive) whenever.
#
#   bash tools/make-gifs.sh
set -euo pipefail
cd "$(dirname "$0")/.."
G=static/gifs
B=static/buttons
mkdir -p "$G" "$B"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

SANS=Liberation-Sans-Bold
MONO=Liberation-Mono-Bold

# 16x16 twinkling star (3 frames: big, small, off).
star() {  # size -> 4-point star polygon centred in 16x16
  local s=$1
  echo "polygon 8,$((8-s)) 9,7 $((8+s)),8 9,9 8,$((8+s)) 7,9 $((8-s)),8 7,7"
}
magick -dispose background -delay 25 \
  \( -size 16x16 xc:none -fill '#fff04a' -stroke '#c08000' -draw "$(star 7)" \) \
  \( -size 16x16 xc:none -fill '#ffffff' -stroke '#c0c000' -draw "$(star 4)" \) \
  \( -size 16x16 xc:none -delay 15 \) \
  -loop 0 "$G/star-blink.gif"

# "NEW!" badge, flashing red/yellow.
newframe() {  # bg fg
  magick -size 30x13 "xc:$1" +antialias -font "$SANS" -pointsize 10 \
    -fill "$2" -gravity center -annotate +0+0 'NEW!' miff:-
}
magick -delay 40 <(newframe '#d00000' '#ffff00') <(newframe '#ffff00' '#d00000') \
  -loop 0 "$G/new.gif"

# Rainbow divider that shimmers along (4 frames, 240x6).
magick -size 240x6 xc:red -colorspace HSL -channel R -fx 'i/w' +channel \
  -colorspace sRGB "$TMP/rainbow.png"
magick -delay 12 "$TMP/rainbow.png" \
  \( "$TMP/rainbow.png" -roll +60+0 \) \( "$TMP/rainbow.png" -roll +120+0 \) \
  \( "$TMP/rainbow.png" -roll +180+0 \) -loop 0 "$G/divider.gif"

# 88x31 buttons: bevelled box, two lines of text.
button() {  # out bg fg line1 line2 [accent]
  local out=$1 bg=$2 fg=$3 l1=$4 l2=$5 acc=${6:-$3}
  magick -size 88x31 "xc:$bg" \
    -fill none -stroke '#ffffff' -draw 'line 0,0 87,0' -draw 'line 0,0 0,30' \
    -stroke '#000000' -draw 'line 0,30 87,30' -draw 'line 87,0 87,30' \
    -stroke "$acc" -draw 'rectangle 2,2 85,28' -stroke none \
    +antialias -font "$MONO" -gravity center \
    -pointsize 11 -fill "$fg" -annotate +0-6 "$l1" \
    -pointsize 11 -fill "$acc" -annotate +0+6 "$l2" \
    "$out"
}

# Your own button, for other people to link back to you. Two frames so the
# second line blinks.
button $TMP/jmg1.gif '#735d78' '#f7d1cd' 'JUSTIN' 'GARRIGUS' '#ffe600'
button $TMP/jmg2.gif '#735d78' '#f7d1cd' 'JUSTIN' 'GARRIGUS' '#ff66ff'
magick -delay 60 $TMP/jmg1.gif $TMP/jmg2.gif -loop 0 "$B/justinmgarrigus.gif"

button "$B/anybrowser.gif"   '#000000' '#ffffff' 'BEST VIEWED' 'ANY BROWSER' '#39ff14'
button "$B/markdown.gif"     '#ffffff' '#000000' 'WRITTEN IN'  'MARKDOWN'    '#0000ee'
button "$B/no-tracking.gif"   '#004400' '#ccffcc' 'NO COOKIES' 'NO TRACKING' '#ffe600'
button "$B/utexas.gif"       '#bf5700' '#ffffff' 'PHD @'       'UT AUSTIN'   '#ffffff'

echo "wrote: $(ls "$G"/*.gif "$B"/*.gif | tr '\n' ' ')"
