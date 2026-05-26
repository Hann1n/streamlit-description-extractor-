from __future__ import annotations

import base64
import html
import json
import struct
import tempfile
from dataclasses import asdict
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


st.set_page_config(
    page_title="PDF DESCRIPTION 추출",
    page_icon="",
    layout="wide",
)


def png_size(image_bytes: bytes) -> tuple[int, int]:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(image_bytes) >= 24:
        return struct.unpack(">II", image_bytes[16:24])
    return 1, 1


def run_extract(
    pdf_bytes: bytes,
    filename: str,
    include_all_lines: bool,
    dpi: int,
    progress_callback=None,
):
    from scripts.extract_description_column import extract_descriptions

    with tempfile.TemporaryDirectory(prefix="desc_streamlit_") as tmp:
        tmp_dir = Path(tmp)
        input_pdf = tmp_dir / filename
        output_txt = tmp_dir / "descriptions.txt"
        output_json = tmp_dir / "descriptions.json"
        debug_dir = tmp_dir / "debug"

        input_pdf.write_bytes(pdf_bytes)

        items = extract_descriptions(
            pdf_path=input_pdf,
            output_txt=output_txt,
            output_json=output_json,
            dpi=dpi,
            first_line_only=not include_all_lines,
            debug_dir=debug_dir,
            progress_callback=progress_callback,
        )

        overlays = []
        for image_path in sorted(debug_dir.glob("*_description_column.png")):
            page_key = image_path.name.replace("_description_column.png", "")
            original_path = debug_dir / f"{page_key}_original_overlay.png"
            page_num = int(page_key.replace("page_", ""))
            upright_bytes = image_path.read_bytes()
            width, height = png_size(upright_bytes)
            page_items = [
                {
                    "row": item.row,
                    "text": item.text,
                    "raw_text": item.raw_text,
                    "bbox": item.bbox,
                }
                for item in items
                if item.page == page_num
            ]
            overlays.append(
                {
                    "name": page_key,
                    "upright_bytes": upright_bytes,
                    "original_bytes": original_path.read_bytes() if original_path.exists() else None,
                    "width": width,
                    "height": height,
                    "items": page_items,
                }
            )

        return items, output_txt.read_text(encoding="utf-8"), output_json.read_text(encoding="utf-8"), overlays


def render_interactive_overlay(overlay: dict) -> None:
    image_base64 = base64.b64encode(overlay["upright_bytes"]).decode("ascii")
    width = max(1, int(overlay.get("width", 1)))
    height = max(1, int(overlay.get("height", 1)))

    box_html = []
    for item in overlay.get("items", []):
        x1, y1, x2, y2 = item["bbox"]
        left = x1 / width * 100
        top = y1 / height * 100
        box_width = max(0.1, (x2 - x1) / width * 100)
        box_height = max(0.1, (y2 - y1) / height * 100)
        text = item.get("text", "")
        raw_text = item.get("raw_text") or text
        escaped_text = html.escape(text, quote=True)
        escaped_raw = html.escape(raw_text, quote=True)
        box_html.append(
            f"""
            <button
              class="desc-box"
              style="left:{left:.5f}%; top:{top:.5f}%; width:{box_width:.5f}%; height:{box_height:.5f}%;"
              data-copy="{escaped_text}"
              aria-label="{escaped_text}"
            >
              <span class="tooltip"><strong>{escaped_text}</strong><br><small>{escaped_raw}</small><br><em>클릭하면 복사됩니다</em></span>
            </button>
            """
        )

    viewer_html = f"""
    <style>
      .viewer-wrap {{
        width: 100%;
        max-height: 760px;
        overflow: auto;
        border: 1px solid #d5d9e2;
        border-radius: 8px;
        background: #f7f8fb;
      }}
      .image-stage {{
        position: relative;
        width: 100%;
        min-width: 760px;
      }}
      .image-stage img {{
        display: block;
        width: 100%;
        height: auto;
      }}
      .desc-box {{
        position: absolute;
        border: 2px solid #ef4444;
        background: rgba(239, 68, 68, 0.08);
        cursor: copy;
        padding: 0;
      }}
      .desc-box:hover {{
        background: rgba(239, 68, 68, 0.20);
        outline: 3px solid rgba(239, 68, 68, 0.35);
        z-index: 20;
      }}
      .tooltip {{
        display: none;
        position: absolute;
        left: 0;
        top: 100%;
        min-width: 220px;
        max-width: 360px;
        transform: translateY(8px);
        background: #111827;
        color: white;
        border-radius: 6px;
        padding: 8px 10px;
        font: 13px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        text-align: left;
        white-space: normal;
        box-shadow: 0 10px 24px rgba(0,0,0,.22);
        pointer-events: none;
      }}
      .desc-box:hover .tooltip {{
        display: block;
      }}
      .copy-toast {{
        position: sticky;
        top: 8px;
        z-index: 50;
        width: fit-content;
        margin: 8px;
        padding: 7px 10px;
        border-radius: 6px;
        background: #0f766e;
        color: white;
        font: 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        display: none;
      }}
    </style>
    <div class="viewer-wrap">
      <div id="copy-toast" class="copy-toast">복사됨</div>
      <div class="image-stage">
        <img src="data:image/png;base64,{image_base64}" alt="DESCRIPTION 위치 확인" />
        {''.join(box_html)}
      </div>
    </div>
    <script>
      const toast = document.getElementById("copy-toast");
      document.querySelectorAll(".desc-box").forEach((box) => {{
        box.addEventListener("click", async () => {{
          const text = box.dataset.copy || "";
          try {{
            await navigator.clipboard.writeText(text);
          }} catch (error) {{
            const textarea = document.createElement("textarea");
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand("copy");
            textarea.remove();
          }}
          toast.textContent = `"${{text}}" 복사됨`;
          toast.style.display = "block";
          window.clearTimeout(window.__copyToastTimer);
          window.__copyToastTimer = window.setTimeout(() => {{
            toast.style.display = "none";
          }}, 1600);
        }});
      }});
    </script>
    """
    components.html(viewer_html, height=800, scrolling=True)


st.title("PDF DESCRIPTION 추출")

with st.sidebar:
    st.header("1. 파일 업로드")
    upload_mode = st.radio(
        "업로드 방식",
        ["PDF 파일", "PDF 폴더"],
        horizontal=True,
    )

    file_uploads = None
    folder_uploads = None

    if upload_mode == "PDF 파일":
        file_uploads = st.file_uploader(
            "PDF 파일 선택",
            type=["pdf"],
            accept_multiple_files=True,
            key="pdf_files",
        )
    else:
        folder_uploads = st.file_uploader(
            "PDF 폴더 선택",
            type=["pdf"],
            accept_multiple_files="directory",
            key="pdf_folder",
        )

    uploads = []
    if file_uploads:
        uploads.extend(file_uploads)
    if folder_uploads:
        uploads.extend(folder_uploads)

    pdf_uploads = [file for file in uploads if file.name.lower().endswith(".pdf")]

    if uploads and not pdf_uploads:
        st.warning("업로드된 파일 중 PDF가 없습니다.")
    elif pdf_uploads:
        st.caption(f"처리 대상 PDF: {len(pdf_uploads)}개")
        with st.expander("대상 파일", expanded=False):
            for uploaded in pdf_uploads:
                st.write(uploaded.name)
    else:
        st.info("PDF 파일 또는 폴더를 업로드하세요.")

    st.divider()
    st.header("2. OCR 옵션")
    include_all_lines = st.checkbox(
        "DESCRIPTION 셀 전체 줄 포함",
        value=False,
        help="끄면 각 DESCRIPTION 셀의 첫 번째 줄만 추출합니다.",
    )
    dpi = st.selectbox(
        "PDF 변환 해상도",
        [200, 300, 400],
        index=0,
        help="기본값 200이 가장 빠릅니다. 표 글자가 작거나 OCR이 누락되면 300 또는 400으로 올리세요.",
    )

    st.divider()
    st.header("3. 실행")
    run_clicked = st.button(
        "DESCRIPTION 추출",
        type="primary",
        use_container_width=True,
        disabled=not pdf_uploads,
    )

    progress = st.empty()
    status = st.empty()

st.subheader("결과")
result_placeholder = st.container()

if run_clicked:
    all_results = []
    text_blocks = []
    progress_bar = progress.progress(0)
    progress_log: list[str] = []
    progress_status = result_placeholder.empty()
    progress_detail = result_placeholder.empty()

    def show_progress(message: str) -> None:
        progress_status.info(message)
        if not progress_log or progress_log[-1] != message:
            progress_log.append(message)
        progress_detail.text_area(
            "진행 상황",
            value="\n".join(progress_log[-14:]),
            height=220,
            disabled=True,
        )

    for idx, uploaded in enumerate(pdf_uploads, start=1):
        show_progress(f"{idx}/{len(pdf_uploads)} 파일 처리 시작: {uploaded.name}")
        status.write(f"{idx}/{len(pdf_uploads)} 처리 중: {uploaded.name}")

        def update_file_progress(event: dict, file_index: int = idx, filename: str = uploaded.name) -> None:
            total_files = max(1, len(pdf_uploads))
            total_pages = int(event.get("total_pages") or 0)
            page = int(event.get("page") or 0)
            if total_pages > 0 and page > 0:
                page_fraction = min(1.0, max(0.0, page / total_pages))
                overall = ((file_index - 1) + page_fraction) / total_files
            else:
                overall = (file_index - 1) / total_files
            progress_bar.progress(min(1.0, max(0.0, overall)))

            message = str(event.get("message") or "처리 중")
            status.write(message)
            show_progress(f"{filename} - {message}")

        try:
            items, text_output, json_output, overlays = run_extract(
                uploaded.getvalue(),
                Path(uploaded.name).name,
                include_all_lines=include_all_lines,
                dpi=dpi,
                progress_callback=update_file_progress,
            )
        except Exception as exc:
            show_progress(f"{uploaded.name} - 오류: {exc}")
            all_results.append(
                {
                    "file": uploaded.name,
                    "error": str(exc),
                    "items": [],
                }
            )
            text_blocks.append(f"[{uploaded.name}]\nERROR: {exc}")
        else:
            show_progress(f"{uploaded.name} - 완료: {len(items)}개 DESCRIPTION 추출")
            all_results.append(
                {
                    "file": uploaded.name,
                    "error": None,
                    "items": items,
                    "json": json_output,
                    "overlays": overlays,
                }
            )
            block = text_output.strip()
            if block:
                text_blocks.append(f"[{uploaded.name}]\n{block}")
            else:
                text_blocks.append(f"[{uploaded.name}]\n")
        progress_bar.progress(idx / len(pdf_uploads))

    status.write("처리 완료")
    show_progress("전체 처리 완료")

    combined_text = "\n\n".join(text_blocks).strip() + "\n"
    combined_json = {
        "total_files": len(all_results),
        "total_items": sum(len(result.get("items", [])) for result in all_results),
        "files": [
            {
                "file": result["file"],
                "error": result.get("error"),
                "items": [asdict(item) for item in result.get("items", [])],
            }
            for result in all_results
        ],
    }
    st.session_state["results"] = all_results
    st.session_state["text_output"] = combined_text
    st.session_state["json_output"] = json.dumps(combined_json, ensure_ascii=False, indent=2)
    st.session_state["overlay_page_index"] = 0

with result_placeholder:
    if "text_output" not in st.session_state:
        st.info("왼쪽 패널에 PDF 또는 폴더를 업로드하고 추출을 실행하면 결과가 여기에 표시됩니다.")
    else:
        results = st.session_state["results"]
        text_output = st.session_state["text_output"]
        total_items = sum(len(result.get("items", [])) for result in results)
        failed = [result for result in results if result.get("error")]
        successful = [result for result in results if not result.get("error")]

        if failed:
            st.warning(f"{total_items}개 DESCRIPTION 항목을 추출했습니다. 실패한 PDF: {len(failed)}개")
        else:
            st.success(f"{total_items}개 DESCRIPTION 항목을 추출했습니다.")

        m1, m2, m3 = st.columns(3)
        m1.metric("처리 PDF", f"{len(results)}개")
        m2.metric("성공", f"{len(successful)}개")
        m3.metric("추출 항목", f"{total_items}개")

        if failed:
            with st.expander("실패한 PDF 확인", expanded=True):
                for result in failed:
                    st.error(f"{result['file']}: {result['error']}")

        st.text_area(
            "복사용 텍스트",
            value=text_output,
            height=420,
        )

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "TXT 다운로드",
                data=text_output.encode("utf-8"),
                file_name="descriptions.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with col2:
            st.download_button(
                "JSON 다운로드",
                data=st.session_state.get("json_output", "").encode("utf-8"),
                file_name="descriptions.json",
                mime="application/json",
                use_container_width=True,
            )

        with st.expander("추출 항목 확인"):
            rows = []
            for result in results:
                for item in result.get("items", []):
                    rows.append(
                        {
                            "file": result["file"],
                            "page": item.page,
                            "row": item.row,
                            "description": item.text,
                            "raw_text": item.raw_text,
                        }
                    )
            st.dataframe(rows, use_container_width=True, hide_index=True)

        with st.expander("원본 위치 확인", expanded=False):
            overlay_options = []
            overlay_map = {}
            for result in results:
                for overlay in result.get("overlays", []):
                    label = f"{result['file']} - {overlay['name']}"
                    overlay_options.append(label)
                    overlay_map[label] = overlay

            if not overlay_options:
                st.info("표시할 원본 위치 이미지가 없습니다.")
            else:
                view_mode = st.radio(
                    "표시 방향",
                    ["정방향 보기", "원본 방향 보기"],
                    horizontal=True,
                )
                if "overlay_page_index" not in st.session_state:
                    st.session_state["overlay_page_index"] = 0

                def clamp_overlay_index() -> None:
                    max_index = max(0, len(overlay_options) - 1)
                    current = st.session_state.get("overlay_page_index", 0)
                    if not isinstance(current, int):
                        current = 0
                    st.session_state["overlay_page_index"] = max(0, min(current, max_index))

                clamp_overlay_index()

                prev_col, select_col, next_col = st.columns([0.18, 0.64, 0.18])
                with prev_col:
                    if st.button(
                        "이전",
                        use_container_width=True,
                        disabled=st.session_state["overlay_page_index"] <= 0,
                    ):
                        st.session_state["overlay_page_index"] -= 1
                with next_col:
                    if st.button(
                        "다음",
                        use_container_width=True,
                        disabled=st.session_state["overlay_page_index"] >= len(overlay_options) - 1,
                    ):
                        st.session_state["overlay_page_index"] += 1
                clamp_overlay_index()
                with select_col:
                    selected_overlay = st.selectbox(
                        "페이지 선택",
                        overlay_options,
                        index=st.session_state["overlay_page_index"],
                        label_visibility="collapsed",
                    )
                    st.session_state["overlay_page_index"] = overlay_options.index(selected_overlay)

                overlay = overlay_map[selected_overlay]
                caption = (
                    "표를 읽기 쉬운 정방향으로 회전해 표시했습니다. 박스에 마우스를 올리면 텍스트가 보이고, 클릭하면 복사됩니다."
                    if view_mode == "정방향 보기"
                    else "원본 PDF 방향 위에 DESCRIPTION 셀 위치를 표시했습니다."
                )
                st.caption(caption)
                if view_mode == "정방향 보기":
                    render_interactive_overlay(overlay)
                else:
                    st.image(
                        overlay.get("original_bytes") or overlay["upright_bytes"],
                        caption=caption,
                        use_container_width=True,
                    )
