#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-v1.0.0-rc1}"
OUT_DIR="${ROOT_DIR}/dist/release-assets/${VERSION}"

rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

runtime_zip="${OUT_DIR}/lcc-claw-node-qpy-${VERSION}-runtime.zip"
examples_zip="${OUT_DIR}/lcc-claw-node-qpy-${VERSION}-examples.zip"
docs_zip="${OUT_DIR}/lcc-claw-node-qpy-${VERSION}-docs.zip"
checksums_txt="${OUT_DIR}/SHA256SUMS.txt"

ditto -c -k --sequesterRsrc --keepParent \
  "${ROOT_DIR}/usr_mirror" \
  "${runtime_zip}"

ditto -c -k --sequesterRsrc --keepParent \
  "${ROOT_DIR}/examples" \
  "${examples_zip}"

tmp_docs_dir="${OUT_DIR}/docs-bundle"
mkdir -p "${tmp_docs_dir}"
cp "${ROOT_DIR}/README.md" "${tmp_docs_dir}/README.md"
cp -R "${ROOT_DIR}/docs" "${tmp_docs_dir}/docs"
ditto -c -k --sequesterRsrc --keepParent \
  "${tmp_docs_dir}" \
  "${docs_zip}"
rm -rf "${tmp_docs_dir}"

(
  cd "${OUT_DIR}"
  shasum -a 256 \
    "$(basename "${runtime_zip}")" \
    "$(basename "${examples_zip}")" \
    "$(basename "${docs_zip}")" \
    > "${checksums_txt}"
)

printf 'release assets generated under %s\n' "${OUT_DIR}"
printf '%s\n' \
  "${runtime_zip}" \
  "${examples_zip}" \
  "${docs_zip}" \
  "${checksums_txt}"
