import io
import json
import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import fitz  # PyMuPDF
from PIL import Image, ImageTk
from pypdf import PdfReader, PdfWriter

CONFIG_FILE = "config.json"


class ToolTip:
    """Classe per gestire il popup informativo al passaggio del mouse."""

    def __init__(self, widget):
        self.widget = widget
        self.tip_window = None

    def show_tip(self, text, x, y):
        self.hide_tip()
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x+15}+{y+10}")

        label = tk.Label(
            tw,
            text=text,
            justify=tk.LEFT,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            font=("Arial", 9, "normal"),
            padx=5,
            pady=3,
        )
        label.pack(ipadx=1)

    def hide_tip(self):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


def sanitize_filename(filename):
    """Rimuove tutti i caratteri non ammessi nei nomi di file (Windows/Linux/Mac)
    ed elimina eventuali spazi doppi o spuri.
    """
    if not filename:
        return ""
    cleaned = re.sub(r'[\\/*?:"<>|]', "", filename)
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def clean_title_parentheses(title):
    """Rimuove le parentesi tonde e il loro contenuto dal titolo,
    e applica la pulizia dai caratteri non ammessi.
    """
    if not title:
        return ""
    cleaned = re.sub(r"\([^)]*\)", "", title)
    return sanitize_filename(cleaned)


def extract_epub_metadata(epub_path):
    try:
        with ZipFile(epub_path, "r") as zip_ref:
            container = zip_ref.read("META-INF/container.xml")
            root = ET.fromstring(container)
            opf_path = root.find(".//{*}rootfile").attrib["full-path"]

            opf_data = zip_ref.read(opf_path)
            opf_root = ET.fromstring(opf_data)

            ns = {"dc": "http://purl.org/dc/elements/1.1/"}
            title_elem = opf_root.find(".//dc:title", ns)
            author_elem = opf_root.find(".//dc:creator", ns)

            title = title_elem.text if title_elem is not None else ""
            author = author_elem.text if author_elem is not None else ""
            return title.strip(), author.strip(), False, ""
    except Exception as e:
        return "", "", True, f"Errore lettura EPUB: struttura ZIP o metadati OPF non validi ({e})"


def extract_pdf_metadata(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        meta = reader.metadata
        title = meta.title if meta and meta.title else ""
        author = meta.author if meta and meta.author else ""
        return title.strip(), author.strip(), False, ""
    except Exception as e:
        return "", "", True, f"Errore lettura PDF: file danneggiato o protetto da password ({e})"


def update_epub_metadata(epub_path, new_title, new_author):
    temp_epub = epub_path + ".tmp"
    try:
        with ZipFile(epub_path, "r") as zin:
            container = zin.read("META-INF/container.xml")
            root = ET.fromstring(container)
            opf_path = root.find(".//{*}rootfile").attrib["full-path"]

            with ZipFile(temp_epub, "w") as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == opf_path:
                        ET.register_namespace(
                            "dc", "http://purl.org/dc/elements/1.1/"
                        )
                        opf_root = ET.fromstring(data)
                        ns = {"dc": "http://purl.org/dc/elements/1.1/"}

                        title_elem = opf_root.find(".//dc:title", ns)
                        if title_elem is not None:
                            title_elem.text = new_title
                        else:
                            metadata_elem = opf_root.find(".//{*}metadata")
                            if metadata_elem is not None:
                                new_t = ET.SubElement(
                                    metadata_elem,
                                    "{http://purl.org/dc/elements/1.1/}title",
                                )
                                new_t.text = new_title

                        author_elem = opf_root.find(".//dc:creator", ns)
                        if author_elem is not None:
                            author_elem.text = new_author
                        else:
                            metadata_elem = opf_root.find(".//{*}metadata")
                            if metadata_elem is not None:
                                new_a = ET.SubElement(
                                    metadata_elem,
                                    "{http://purl.org/dc/elements/1.1/}creator",
                                )
                                new_a.text = new_author

                        data = ET.tostring(
                            opf_root, encoding="utf-8", xml_declaration=True
                        )
                    zout.writestr(item, data)

        os.replace(temp_epub, epub_path)
        return True, ""
    except Exception as e:
        if os.path.exists(temp_epub):
            os.remove(temp_epub)
        return False, f"Impossibile aggiornare i metadati EPUB: {e}"


def update_pdf_metadata(pdf_path, new_title, new_author):
    temp_pdf = pdf_path + ".tmp"
    try:
        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        writer.append(reader)

        metadata = reader.metadata or {}
        new_meta = {k: v for k, v in metadata.items()}
        new_meta["/Title"] = new_title
        new_meta["/Author"] = new_author

        writer.add_metadata(new_meta)

        with open(temp_pdf, "wb") as f:
            writer.write(f)

        os.replace(temp_pdf, pdf_path)
        return True, ""
    except Exception as e:
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
        return False, f"Impossibile aggiornare i metadati PDF: {e}"


def render_page_image(doc, page_num, zoom_factor=1.0, base_height=420):
    try:
        if page_num < len(doc):
            page = doc[page_num]
            target_height = int(base_height * zoom_factor)
            pix = page.get_pixmap(dpi=int(100 * zoom_factor))
            img = Image.open(io.BytesIO(pix.tobytes("png")))

            w_percent = target_height / float(img.size[1])
            target_width = int(float(img.size[0]) * float(w_percent))
            img = img.resize(
                (target_width, target_height), Image.Resampling.LANCZOS
            )

            return ImageTk.PhotoImage(img)
    except Exception as e:
        print(f"Errore rendering pagina: {e}")
    return None


class EbookRenamerApp:

    def __init__(self, root):
        self.root = root
        self.root.title("Gestore e Rinomina EPUB e PDF")

        self.target_folder = ""
        self.ebook_files = []

        self.config = self.load_config()

        geom = self.config.get("window_geometry", "1100x650")
        try:
            self.root.geometry(geom)
        except Exception:
            self.root.geometry("1100x650")

        self.create_widgets()

        self.root.bind("<Configure>", self.on_window_configure)

        last_folder = self.config.get("last_folder", "")
        if last_folder and os.path.exists(last_folder):
            self.target_folder = last_folder
            self.lbl_folder.config(text=last_folder)
            self.load_files()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_window_configure(self, event):
        if event.widget == self.root:
            self.config["window_geometry"] = self.root.geometry()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_config(self):
        col_widths = {
            col: self.tree.column(col, "width")
            for col in ("type", "original", "author", "title", "new_name")
        }
        config_data = {
            "window_geometry": self.root.geometry(),
            "popup_geometry": self.config.get("popup_geometry", "1150x750"),
            "col_widths": col_widths,
            "last_folder": self.target_folder,
        }
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(config_data, f)
        except Exception as e:
            print(f"Impossibile salvare la configurazione: {e}")

    def on_closing(self):
        self.save_config()
        self.root.destroy()

    def create_widgets(self):
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        btn_select = ttk.Button(
            top_frame, text="Seleziona Cartella", command=self.select_folder
        )
        btn_select.pack(side=tk.LEFT, padx=5)

        self.lbl_folder = ttk.Label(
            top_frame, text="Nessuna cartella selezionata", font=("Arial", 9, "italic")
        )
        self.lbl_folder.pack(side=tk.LEFT, padx=10)

        format_frame = ttk.Frame(self.root, padding=5)
        format_frame.pack(fill=tk.X)

        ttk.Label(format_frame, text="Schema Nomenclatura:").pack(
            side=tk.LEFT, padx=10
        )
        self.format_var = tk.StringVar(value="Autore - Titolo")
        format_combo = ttk.Combobox(
            format_frame,
            textvariable=self.format_var,
            values=["Autore - Titolo", "Titolo - Autore", "Titolo"],
            state="readonly",
            width=20,
        )
        format_combo.pack(side=tk.LEFT, padx=5)
        format_combo.bind("<<ComboboxSelected>>", lambda e: self.update_preview_names())

        # --- PANNELLO LEGENDA COLORI ---
        legend_frame = ttk.LabelFrame(self.root, text=" Legenda Colori Tabella ", padding=(10, 5))
        legend_frame.pack(fill=tk.X, padx=10, pady=5)

        items_legend = [
            ("#ff4d4d", "#ffffff", "Errore lettura / file non valido"),
            ("#fff3cd", "#856404", "Autore generato in automatico (primi 20 car.)"),
            ("#2e7d32", "#ffffff", "Modificato manualmente dall'utente"),
            ("#795548", "#ffffff", "File contrassegnato per l'eliminazione"),
            ("#ffffff", "#000000", "Standard / Nessuna modifica"),
        ]

        for bg, fg, text in items_legend:
            item_box = ttk.Frame(legend_frame)
            item_box.pack(side=tk.LEFT, padx=8, pady=2)

            color_sample = tk.Label(
                item_box,
                text="   ",
                bg=bg,
                relief=tk.SOLID,
                borderwidth=1,
            )
            color_sample.pack(side=tk.LEFT, padx=(0, 5))

            lbl_desc = ttk.Label(item_box, text=text, font=("Arial", 8))
            lbl_desc.pack(side=tk.LEFT)

        tree_frame = ttk.Frame(self.root, padding=10)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("type", "original", "author", "title", "new_name")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )

        self.tree.heading("type", text="Tipo")
        self.tree.heading("original", text="Nome Originale")
        self.tree.heading("author", text="Autore")
        self.tree.heading("title", text="Titolo Metadato")
        self.tree.heading("new_name", text="Nuovo Nome Generato")

        # Configurazione Stili delle Righe
        self.tree.tag_configure("even", background="#ffffff")
        self.tree.tag_configure("odd", background="#d9d9d9")
        self.tree.tag_configure("error", background="#ff4d4d", foreground="#ffffff")
        self.tree.tag_configure("corrected", background="#2e7d32", foreground="#ffffff")  # Verde Scuro
        self.tree.tag_configure("marked_delete", background="#795548", foreground="#ffffff")  # Marrone
        self.tree.tag_configure("auto_mod", background="#fff3cd", foreground="#856404")

        saved_widths = self.config.get("col_widths", {})
        default_widths = {
            "type": 60,
            "original": 220,
            "author": 160,
            "title": 240,
            "new_name": 260,
        }

        for col in columns:
            w = saved_widths.get(col, default_widths[col])
            align = tk.CENTER if col == "type" else tk.W
            self.tree.column(col, width=int(w), anchor=align)

        scrollbar = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self.tree.yview
        )
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", self.on_double_click)

        # Gestione Tooltip al passaggio del mouse
        self.tooltip = ToolTip(self.tree)
        self.tree.bind("<Motion>", self.on_mouse_move)
        self.tree.bind("<Leave>", lambda e: self.tooltip.hide_tip())

        bottom_frame = ttk.Frame(self.root, padding=10)
        bottom_frame.pack(fill=tk.X)

        lbl_info = ttk.Label(
            bottom_frame,
            text="* Passa il mouse su una riga rossa per visualizzare i dettagli del problema.",
            foreground="gray",
        )
        lbl_info.pack(side=tk.LEFT)

        btn_rename = ttk.Button(
            bottom_frame,
            text="Applica, Aggiorna Metadati e Rinomina",
            command=self.rename_all_files,
        )
        btn_rename.pack(side=tk.RIGHT, padx=5)

    def on_mouse_move(self, event):
        item_id = self.tree.identify_row(event.y)
        if item_id:
            idx = int(item_id)
            if idx < len(self.ebook_files):
                item = self.ebook_files[idx]
                if item["has_error"]:
                    err_msg = item.get("error_details", "Errore non specificato.")
                    self.tooltip.show_tip(
                        f"Dettaglio Errore:\n{err_msg}",
                        event.x_root,
                        event.y_root,
                    )
                    return
        self.tooltip.hide_tip()

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.target_folder = folder
            self.lbl_folder.config(text=folder)
            self.load_files()

    def load_files(self):
        self.tree.delete(*self.tree.get_children())
        self.ebook_files.clear()

        loading_win = tk.Toplevel(self.root)
        loading_win.title("Caricamento")
        loading_win.geometry("300x100")
        loading_win.transient(self.root)
        loading_win.grab_set()

        lbl_loading = ttk.Label(
            loading_win,
            text="Caricamento tabella in corso...\nAttendere prego.",
            font=("Arial", 10),
            justify=tk.CENTER,
        )
        lbl_loading.pack(expand=True)
        self.root.update()

        try:
            for filename in os.listdir(self.target_folder):
                ext = os.path.splitext(filename)[1].lower()
                if ext in [".epub", ".pdf"]:
                    file_path = os.path.join(self.target_folder, filename)

                    if ext == ".epub":
                        title, author, has_error, err_msg = extract_epub_metadata(file_path)
                    else:
                        title, author, has_error, err_msg = extract_pdf_metadata(file_path)

                    base_filename = os.path.splitext(filename)[0]
                    if not title:
                        title = base_filename

                    title = clean_title_parentheses(title)

                    is_auto_modified = False
                    if not author or author.strip().lower() == "autore sconosciuto":
                        author = title[:20].strip()
                        is_auto_modified = True

                    author = sanitize_filename(author)

                    item_data = {
                        "ext": ext,
                        "original": filename,
                        "author": author,
                        "title": title,
                        "orig_author": author,
                        "orig_title": title,
                        "new_name": "",
                        "has_error": has_error,
                        "error_details": err_msg,
                        "is_corrected": False,
                        "is_auto_modified": is_auto_modified,
                        "to_delete": False,
                    }
                    self.ebook_files.append(item_data)
        finally:
            loading_win.destroy()

        self.update_preview_names()

    def update_preview_names(self):
        schema = self.format_var.get()
        self.tree.delete(*self.tree.get_children())

        for idx, item in enumerate(self.ebook_files):
            author = item["author"]
            title = item["title"]
            ext = item["ext"]

            if item.get("to_delete", False):
                new_basename = "[DA ELIMINARE]"
            else:
                if schema == "Autore - Titolo":
                    new_basename = f"{author} - {title}{ext}" if author else f"{title}{ext}"
                elif schema == "Titolo - Autore":
                    new_basename = f"{title} - {author}{ext}" if author else f"{title}{ext}"
                else:
                    new_basename = f"{title}{ext}"

                new_basename = sanitize_filename(new_basename)

            item["new_name"] = new_basename

            # Priorità Stili: Marrone (Eliminazione) > Errore (Rosso) > Modifica Manuale (Verde Scuro) > Modifica Automatica (Giallo) > Alternato
            if item.get("to_delete", False):
                row_tag = "marked_delete"
            elif item["has_error"]:
                row_tag = "error"
            elif item["is_corrected"]:
                row_tag = "corrected"
            elif item["is_auto_modified"]:
                row_tag = "auto_mod"
            else:
                row_tag = "even" if idx % 2 == 0 else "odd"

            self.tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    ext.upper().replace(".", ""),
                    item["original"],
                    author,
                    title,
                    new_basename,
                ),
                tags=(row_tag,),
            )

    def on_double_click(self, event):
        item_id = self.tree.selection()
        if not item_id:
            return

        idx = int(item_id[0])
        item_data = self.ebook_files[idx]
        file_path = os.path.join(self.target_folder, item_data["original"])

        try:
            doc = fitz.open(file_path)
            total_pages = len(doc)
        except Exception as e:
            messagebox.showerror(
                "Errore", f"Impossibile aprire il file per l'anteprima.\n{e}"
            )
            return

        edit_win = tk.Toplevel(self.root)
        edit_win.title(f"Dettagli e Lettore Anteprima - {item_data['original']}")

        popup_geom = self.config.get("popup_geometry", "1150x750")
        try:
            edit_win.geometry(popup_geom)
        except Exception:
            edit_win.geometry("1150x750")

        edit_win.transient(self.root)
        edit_win.grab_set()

        def save_popup_geo(event):
            if event.widget == edit_win:
                self.config["popup_geometry"] = edit_win.geometry()

        edit_win.bind("<Configure>", save_popup_geo)

        current_page = [0]
        zoom_level = [1.0]

        top_input_frame = ttk.LabelFrame(
            edit_win, text=" Metadati e Opzioni ", padding=10
        )
        top_input_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        f_author = ttk.Frame(top_input_frame)
        f_author.pack(fill=tk.X, pady=3)
        ttk.Label(f_author, text="Autore:", width=10, anchor=tk.W).pack(
            side=tk.LEFT
        )
        entry_author = ttk.Entry(f_author, width=128)
        entry_author.insert(0, item_data["author"])
        entry_author.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        f_title = ttk.Frame(top_input_frame)
        f_title.pack(fill=tk.X, pady=3)
        ttk.Label(f_title, text="Titolo:", width=10, anchor=tk.W).pack(
            side=tk.LEFT
        )
        entry_title = ttk.Entry(f_title, width=128)
        entry_title.insert(0, item_data["title"])
        entry_title.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Checkbox Elimina File
        var_delete = tk.BooleanVar(value=item_data.get("to_delete", False))
        chk_delete = ttk.Checkbutton(
            top_input_frame,
            text="Segna come file da eliminare (verrà rimosso all'applicazione delle modifiche)",
            variable=var_delete
        )
        chk_delete.pack(anchor=tk.W, pady=5)

        f_save = ttk.Frame(top_input_frame)
        f_save.pack(fill=tk.X, pady=(5, 0))

        lbl_char_count = ttk.Label(
            f_save, text="", font=("Arial", 9, "italic"), foreground="gray"
        )
        lbl_char_count.pack(side=tk.LEFT, padx=5)

        def check_length(*args):
            l_auth = len(sanitize_filename(entry_author.get()))
            cleaned_t = clean_title_parentheses(entry_title.get())
            l_tit = len(cleaned_t)
            total = l_auth + l_tit
            lbl_char_count.config(
                text=f"Totale caratteri (Autore + Titolo): {total} / 128 max"
            )

        entry_author.bind("<KeyRelease>", check_length)
        entry_title.bind("<KeyRelease>", check_length)
        check_length()

        def save_changes():
            to_del = var_delete.get()
            item_data["to_delete"] = to_del

            if not to_del:
                new_a = sanitize_filename(entry_author.get())
                new_t = clean_title_parentheses(entry_title.get())

                if not new_a or new_a.lower() == "autore sconosciuto":
                    new_a = new_t[:20].strip()

                total_len = len(new_a) + len(new_t)

                if total_len > 128:
                    messagebox.showerror(
                        "Errore Validazione",
                        f"La somma dei caratteri di Autore + Titolo supera il limite massimo consentito (128)!\n\n"
                        f"Lunghezza attuale: {total_len} caratteri.\n"
                        f"Correggi i testi prima di salvare.",
                    )
                    return

                item_data["author"] = new_a
                item_data["title"] = new_t
                item_data["has_error"] = False
                item_data["is_corrected"] = True
                item_data["error_details"] = ""

            self.update_preview_names()
            edit_win.destroy()

        btn_save = ttk.Button(
            f_save, text="Salva Modifiche", command=save_changes
        )
        btn_save.pack(side=tk.RIGHT, padx=5)

        preview_frame = ttk.Frame(edit_win, padding=10)
        preview_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)

        controls_frame = ttk.Frame(preview_frame)
        controls_frame.pack(fill=tk.X, pady=(0, 5))

        btn_prev = ttk.Button(controls_frame, text="◄ Precedente")
        btn_prev.pack(side=tk.LEFT, padx=5)

        lbl_page_num = ttk.Label(
            controls_frame, text=f"Pagina 1 / {total_pages}"
        )
        lbl_page_num.pack(side=tk.LEFT, padx=10)

        btn_next = ttk.Button(controls_frame, text="Successiva ►")
        btn_next.pack(side=tk.LEFT, padx=5)

        lbl_zoom = ttk.Label(controls_frame, text="Zoom: 100%")
        lbl_zoom.pack(side=tk.RIGHT, padx=5)

        def update_zoom(delta):
            new_z = round(zoom_level[0] + delta, 1)
            if 0.5 <= new_z <= 2.5:
                zoom_level[0] = new_z
                lbl_zoom.config(text=f"Zoom: {int(zoom_level[0]*100)}%")
                refresh_preview()

        btn_zoom_out = ttk.Button(
            controls_frame, text="-", width=3, command=lambda: update_zoom(-0.2)
        )
        btn_zoom_out.pack(side=tk.RIGHT, padx=2)

        btn_zoom_in = ttk.Button(
            controls_frame, text="+", width=3, command=lambda: update_zoom(0.2)
        )
        btn_zoom_in.pack(side=tk.RIGHT, padx=2)

        canvas_frame = ttk.Frame(preview_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)

        canvas = tk.Canvas(
            canvas_frame,
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set,
            bg="#333333",
        )
        v_scroll.config(command=canvas.yview)
        h_scroll.config(command=canvas.xview)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        image_container = canvas.create_image(0, 0, anchor=tk.NW)

        def refresh_preview():
            p_idx = current_page[0]
            img = render_page_image(
                doc, p_idx, zoom_factor=zoom_level[0], base_height=420
            )
            if img:
                edit_win.current_img = img
                canvas.itemconfig(image_container, image=img)
                canvas.config(
                    scrollregion=(0, 0, img.width(), img.height())
                )
            lbl_page_num.config(
                text=f"Pagina {p_idx + 1} / {total_pages}"
            )

        def go_prev():
            if current_page[0] > 0:
                current_page[0] -= 1
                refresh_preview()

        def go_next():
            if current_page[0] < total_pages - 1:
                current_page[0] += 1
                refresh_preview()

        btn_prev.config(command=go_prev)
        btn_next.config(command=go_next)

        refresh_preview()

    def rename_all_files(self):
        if not self.ebook_files:
            messagebox.showwarning(
                "Attenzione", "Nessun file presente nella lista."
            )
            return

        renamed_count = 0
        deleted_count = 0
        error_count = 0

        remaining_files = []

        for item in self.ebook_files:
            old_path = os.path.join(self.target_folder, item["original"])

            # Gestione eliminazione file
            if item.get("to_delete", False):
                try:
                    if os.path.exists(old_path):
                        os.remove(old_path)
                    deleted_count += 1
                    continue  # Non lo aggiungiamo ai rimanenti
                except Exception as e:
                    item["has_error"] = True
                    item["error_details"] = f"Impossibile eliminare il file: {e}"
                    error_count += 1
                    remaining_files.append(item)
                    continue

            meta_ok = True
            err_details = ""

            if (
                item["author"] != item["orig_author"]
                or item["title"] != item["orig_title"]
            ):
                if item["ext"] == ".epub":
                    meta_ok, err_details = update_epub_metadata(
                        old_path, item["title"], item["author"]
                    )
                elif item["ext"] == ".pdf":
                    meta_ok, err_details = update_pdf_metadata(
                        old_path, item["title"], item["author"]
                    )

            new_path = os.path.join(self.target_folder, item["new_name"])
            if old_path != new_path:
                try:
                    os.rename(old_path, new_path)
                    item["original"] = item["new_name"]
                    if not meta_ok:
                        item["has_error"] = True
                        item["error_details"] = err_details
                        error_count += 1
                    else:
                        item["has_error"] = False
                        renamed_count += 1
                except Exception as e:
                    item["has_error"] = True
                    item["error_details"] = f"Impossibile rinominare il file: {e}"
                    error_count += 1
            else:
                if not meta_ok:
                    item["has_error"] = True
                    item["error_details"] = err_details
                    error_count += 1

            remaining_files.append(item)

        self.ebook_files = remaining_files

        msg = f"File rinominati/elaborati: {renamed_count}\nFile eliminati: {deleted_count}"
        if error_count > 0:
            msg += f"\nErrori riscontrati: {error_count}"

        messagebox.showinfo("Operazione completata", msg)
        self.update_preview_names()


if __name__ == "__main__":
    root = tk.Tk()
    app = EbookRenamerApp(root)
    root.mainloop()