"""Template manifest contracts (DATA_MODELS §5, ADR-007). Geometry is in EMU."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from docforge.models.base import DFModel, VersionedDocument
from docforge.models.intent import OutputFormat


class Box(DFModel):
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def area(self) -> int:
        return max(self.w, 0) * max(self.h, 0)

    def intersection_area(self, other: Box) -> int:
        dx = min(self.right, other.right) - max(self.x, other.x)
        dy = min(self.bottom, other.bottom) - max(self.y, other.y)
        return dx * dy if dx > 0 and dy > 0 else 0

    def inside(self, other: Box, tolerance: int = 0) -> bool:
        return (
            self.x >= other.x - tolerance
            and self.y >= other.y - tolerance
            and self.right <= other.right + tolerance
            and self.bottom <= other.bottom + tolerance
        )


class ThemeSpec(DFModel):
    colors: dict[str, str] = Field(
        default_factory=dict, description="Theme slots dk1, lt1, accent1..6 -> hex"
    )
    major_font: str | None = None
    minor_font: str | None = None


class ElementKind(StrEnum):
    text = "text"
    picture = "picture"
    shape = "shape"
    group = "group"
    table = "table"
    chart = "chart"
    line = "line"
    placeholder = "placeholder"
    other = "other"


class ElementRole(StrEnum):
    structural = "structural"
    branding = "branding"
    decorative = "decorative"
    placeholder = "placeholder"
    sample_content = "sample_content"


class PropertySource(StrEnum):
    explicit = "explicit"
    inherited = "inherited"
    unknown = "unknown"


class FontSpec(DFModel):
    name: str | None = None
    size_pt: float | None = None
    bold: bool | None = None
    color: str | None = None
    name_source: PropertySource = PropertySource.unknown
    size_source: PropertySource = PropertySource.unknown
    bold_source: PropertySource = PropertySource.unknown
    color_source: PropertySource = PropertySource.unknown


class ElementSpec(DFModel):
    id: str
    name: str
    kind: ElementKind
    bbox: Box | None = None
    z: int = 0
    role: ElementRole = ElementRole.decorative
    text: str | None = None
    fill: str | None = None
    fill_source: PropertySource = PropertySource.unknown
    font: FontSpec | None = None
    bbox_source: PropertySource = PropertySource.unknown
    placeholder_type: str | None = None
    placeholder_idx: int | None = None


class LayoutArchetype(StrEnum):
    title = "title"
    section = "section"
    bullets = "bullets"
    two_column = "two_column"
    comparison = "comparison"
    image_text = "image_text"
    title_only = "title_only"
    blank = "blank"
    content = "content"
    closing = "closing"
    other = "other"


class PlaceholderSpec(DFModel):
    idx: int
    type: str
    name: str = ""
    bbox: Box | None = None
    bbox_source: PropertySource = PropertySource.unknown
    font: FontSpec | None = None


class LayoutSpec(DFModel):
    id: str
    name: str
    master_index: int = 0
    archetype: LayoutArchetype = LayoutArchetype.other
    placeholders: list[PlaceholderSpec] = Field(default_factory=list)
    elements: list[ElementSpec] = Field(default_factory=list)


class SlideInventory(DFModel):
    index: int
    layout_id: str
    elements: list[ElementSpec] = Field(default_factory=list)


class SlideBase(DFModel):
    """A sample slide reusable as a designed base (template design mode "slides")."""

    index: int
    kind: str = Field(description="cover | section | content | closing")
    title_shape: int | None = Field(None, description="index in slide.shapes of the title text box")
    subtitle_shape: int | None = None
    remove_shapes: list[int] = Field(default_factory=list, description="sample text/content to drop")
    photo_shapes: list[int] = Field(default_factory=list, description="empty picture placeholders")
    frame_shapes: list[int] = Field(default_factory=list, description="plain light boxes that frame a photo")
    region: Box | None = Field(None, description="content area freed by the removed sample text")
    score: float = 0.0
    title_text: str = ""
    region_color: str | None = Field(None, description="colour behind the content region")
    region_color: str | None = Field(None, description="colour behind the content region")


class PptxTemplateInfo(DFModel):
    slide_width: int
    slide_height: int
    master_count: int = 1
    layouts: list[LayoutSpec] = Field(default_factory=list)
    sample_slides: list[SlideInventory] = Field(default_factory=list)
    design_mode: str = Field("layouts", description="layouts | slides (artwork lives on sample slides)")
    slide_bases: list[SlideBase] = Field(default_factory=list)
    slide_fonts: dict[str, str] = Field(default_factory=dict, description="heading/body fonts used on slides")
    slide_palette: list[str] = Field(
        default_factory=list, description="accent colours taken from the artwork"
    )
    slide_text_color: str | None = None
    slide_background: str | None = None


class StyleInfo(DFModel):
    name: str
    style_id: str
    type: str
    based_on: str | None = None
    font: FontSpec | None = None
    in_use: bool = False


class HeaderFooterElementInfo(DFModel):
    """One element found inside a header or footer."""

    kind: str = Field(description="text | image | table | field")
    text: str | None = None
    field_code: str | None = Field(None, description="e.g. PAGE, NUMPAGES, DATE")
    image_asset_key: str | None = Field(None, description="key into DocxTemplateInfo.image_assets")
    width_emu: int | None = None
    height_emu: int | None = None


class HeaderFooterInfo(DFModel):
    """Detailed content of one header or footer part."""

    present: bool = False
    text: str = ""
    elements: list[HeaderFooterElementInfo] = Field(default_factory=list)
    has_table: bool = False
    has_image: bool = False


class ImageAssetInfo(DFModel):
    """An image extracted from the DOCX template."""

    asset_key: str = Field(description="Unique key for this asset within the template")
    original_rel_id: str = ""
    content_type: str = ""
    location: str = Field(description="header | footer | body")
    section_index: int = 0
    width_emu: int | None = None
    height_emu: int | None = None
    description: str = ""
    is_logo: bool = Field(False, description="Heuristic: image in header/footer, small, branded")
    blob_sha256: str = Field("", description="SHA256 hash of image data")
    file_path: str | None = Field(None, description="Path where asset blob is cached, if any")


class SectionInfo(DFModel):
    page_width: int
    page_height: int
    orientation: str = "portrait"
    margins: dict[str, int] = Field(default_factory=dict)
    header_text: str = ""
    footer_text: str = ""
    has_page_number: bool = False
    different_first_page: bool = False
    # Detailed header/footer breakdown
    default_header: HeaderFooterInfo = Field(default_factory=HeaderFooterInfo)
    default_footer: HeaderFooterInfo = Field(default_factory=HeaderFooterInfo)
    first_page_header: HeaderFooterInfo = Field(default_factory=HeaderFooterInfo)
    first_page_footer: HeaderFooterInfo = Field(default_factory=HeaderFooterInfo)
    even_page_header: HeaderFooterInfo = Field(default_factory=HeaderFooterInfo)
    even_page_footer: HeaderFooterInfo = Field(default_factory=HeaderFooterInfo)
    header_distance_emu: int | None = None
    footer_distance_emu: int | None = None


class DocxTemplateInfo(DFModel):
    styles: list[StyleInfo] = Field(default_factory=list)
    sections: list[SectionInfo] = Field(default_factory=list)
    has_toc: bool = False
    paragraph_count: int = 0
    table_count: int = 0
    role_style_map: dict[str, str] = Field(
        default_factory=dict, description="role (title, h1, body...) -> style name"
    )
    image_assets: list[ImageAssetInfo] = Field(
        default_factory=list, description="Images extracted from the template"
    )
    theme_colors: dict[str, str] = Field(
        default_factory=dict, description="Theme color slots -> hex values"
    )


class SheetInfo(DFModel):
    name: str
    dimensions: str = ""
    max_row: int = 0
    max_column: int = 0
    formula_count: int = 0
    tables: list[str] = Field(default_factory=list)
    charts: int = 0
    role_guess: str = "data"


class XlsxTemplateInfo(DFModel):
    sheets: list[SheetInfo] = Field(default_factory=list)
    defined_names: dict[str, str] = Field(default_factory=dict)


class LayoutGuidance(DFModel):
    layout_id: str
    purpose: str
    constraints: list[str] = Field(default_factory=list)


class ReusableElementGuidance(DFModel):
    element_id: str
    intended_use: str
    preserve_appearance: bool = True
    replace_sample_text: bool = False


class TemplateDesignAnalysis(DFModel):
    summary: str
    typography: dict[str, str] = Field(default_factory=dict)
    color_roles: dict[str, str] = Field(default_factory=dict)
    style_roles: dict[str, str] = Field(default_factory=dict)
    page_rules: list[str] = Field(default_factory=list)
    layouts: list[LayoutGuidance] = Field(default_factory=list)
    preservation_rules: list[str] = Field(default_factory=list)
    reusable_elements: list[ReusableElementGuidance] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class TemplateManifest(VersionedDocument):
    id: str
    format: OutputFormat
    file_sha256: str
    theme: ThemeSpec = Field(default_factory=ThemeSpec)
    pptx: PptxTemplateInfo | None = None
    docx: DocxTemplateInfo | None = None
    xlsx: XlsxTemplateInfo | None = None
    warnings: list[str] = Field(default_factory=list)
    design_guide: dict[str, str] = Field(default_factory=dict, description="External guide files")
    analyzer_version: int = Field(0, description="Cached manifests from older analyzers are recomputed")
    design_analysis: TemplateDesignAnalysis | None = None
    design_analysis_version: int = Field(0, description="Prompt/schema version of cached LLM design analysis")
    design_analysis_model: str | None = None
