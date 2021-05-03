import dataclasses as dc
import shutil
import textwrap
from itertools import chain
from typing import (
    Any, Callable, Dict, Iterable, Optional, Sequence, Tuple, cast,
)

import click
from click._compat import term_len
from click.formatting import iter_rows, wrap_text

from cloup._util import check_positive_int, identity, make_repr

# It's not worth it to require typing_extensions just define this as a Protocol.
FormatterMaker = Callable[..., 'HelpFormatter']

FORMATTER_TYPE_ERROR = """
since cloup v0.8.0, this class relies on cloup.HelpFormatter to align help
sections. So, you need to make sure your command class uses cloup.HelpFormatter
as formatter class.

If you have your own custom HelpFormatter, know that cloup.HelpFormatter is
more easily customizable then Click's one, so consider extending it instead
of extending click.HelpFormatter.
"""


def ensure_is_cloup_formatter(formatter: click.HelpFormatter) -> 'HelpFormatter':
    if isinstance(formatter, HelpFormatter):
        return formatter
    raise TypeError(FORMATTER_TYPE_ERROR)


@dc.dataclass
class HelpSection:
    """A container for a help section data."""
    heading: str

    #: Rows with 2 columns each.
    definitions: Sequence[Tuple[str, str]]

    #: Optional long description of the section.
    description: Optional[str] = None


IStyler = Callable[[str], str]


@dc.dataclass(frozen=True)
class Style:
    fg: Optional[str] = None
    bg: Optional[str] = None
    bold: bool = False
    dim: bool = False
    underline: bool = False
    blink: bool = False
    reverse: bool = False
    text_transform: Optional[IStyler] = None
    _click_kwargs: dict = dc.field(init=False, default_factory=dict)

    def __post_init__(self):
        click_kwargs = dc.asdict(self)
        click_kwargs.pop('text_transform')
        click_kwargs.pop('_click_kwargs')
        object.__setattr__(self, '_click_kwargs', {
            key: (None if not value else value)
            for key, value in click_kwargs.items()
        })

    def __call__(self, text: str) -> str:
        if self.text_transform:
            text = self.text_transform(text)
        return click.style(text, **self._click_kwargs)


@dc.dataclass(frozen=True)
class HelpTheme:
    #: Style of the command name.
    command: IStyler = identity
    #: Style of help section headings.
    heading: IStyler = identity
    col1: IStyler = identity
    col2: IStyler = identity
    epilog: IStyler = identity

    def with_(
        self, command: Optional[IStyler] = None,
        heading: Optional[IStyler] = None,
        col1: Optional[IStyler] = None,
        col2: Optional[IStyler] = None,
        epilog: Optional[IStyler] = None,
    ) -> 'HelpTheme':
        return HelpTheme(
            command = command or self.command,
            heading = heading or self.heading,
            col1 = col1 or self.col1,
            col2 = col2 or self.col2,
            epilog = epilog or self.epilog
        )

    @staticmethod
    def dark():
        return HelpTheme(
            command=Style(fg='bright_yellow'),
            heading=Style(fg='bright_white'),
            col1=Style(fg='bright_yellow'),
            epilog=Style(fg='bright_white'),
        )


# noinspection PyMethodMayBeStatic
class HelpFormatter(click.HelpFormatter):
    """
    A custom help formatter. Features include:

    - more attributes for controlling the output of the formatter
    - a ``col1_width`` parameter in :meth:`write_dl` that allows to align
      multiple definition lists
    - definition lists are formatted in "wide" (tabular) or "narrow" form depending
      on whether there's enough space to accomodate the 2nd column (the minimum
      width for the 2nd columns is ``col2_min_width``)
    - the first column width, when not explicitly given in ``write_dl`` is
      computed excluding the rows that exceed ``col1_max_width``
      (called ``col_max`` in ``write_dl`` for compatibility with Click).

    .. versionadded:: 0.8.0

    :param indent_increment:
        indentation width
    :param width:
        content line width; by default it's initialized as the minimum of
        the terminal width and the argument ``max_width``.
    :param max_width:
        maximum content line width (corresponds to ``Context.max_content_width``.
        Used to compute ``width`` if it is not provided; ignored otherwise.
    :param col1_max_width:
        the maximum width of the first column of a definition list.
    :param col_spacing:
        the (minimum) number of spaces between the columns of a definition list.
    :param row_sep:
        a string printed after each row of a definition list (including the last).
    """

    def __init__(
        self, indent_increment: int = 2,
        width: Optional[int] = None,
        max_width: Optional[int] = 80,
        col1_max_width: int = 30,
        col2_min_width: int = 35,
        col_spacing: int = 2,
        row_sep: str = '',
        theme: HelpTheme = HelpTheme(),
    ):
        check_positive_int(col1_max_width, 'col1_max_width')
        check_positive_int(col_spacing, 'col_spacing')
        self.col1_max_width = col1_max_width
        self.col2_min_width = col2_min_width
        self.col_spacing = col_spacing
        self.row_sep = row_sep
        self.theme = theme
        max_width = max_width or 80
        width = (
            width or click.formatting.FORCED_WIDTH
            or min(max_width, shutil.get_terminal_size((80, 100)).columns)
        )
        super().__init__(
            width=width, max_width=max_width, indent_increment=indent_increment
        )
        self.width: int = width

    @staticmethod
    def opts(
        *, width: Optional[int] = None,
        max_width: Optional[int] = None,
        indent_increment: Optional[int] = None,
        col1_max_width: Optional[int] = None,
        col2_min_width: Optional[int] = None,
        col_spacing: Optional[int] = None,
        row_sep: Optional[str] = None,
        theme: Optional[HelpTheme] = None,
    ) -> Dict[str, Any]:
        """A utility method for creating a ``formatter_opts`` dictionary to
        pass as context settings or command attribute. This method exists for
        one only reason: it enables auto-complete for formatter options, thus
        improving the developer experience."""
        return {key: val for key, val in locals().items() if val is not None}

    @property
    def available_width(self) -> int:
        return cast(int, self.width) - self.current_indent

    def write_usage(self, prog, args="", prefix=None):
        if prefix is None:
            prefix = 'Usage:'
        prefix = self.theme.heading(prefix) + ' '
        prog = self.theme.command(prog)
        super().write_usage(prog, args, prefix)

    def write_heading(self, heading):
        styled_heading = self.theme.heading(heading + ':')
        self.write(" " * self.current_indent + styled_heading + "\n")

    def write_many_sections(
        self, sections: Sequence[HelpSection],
        aligned: bool = True,
        truncate_col2: bool = False,
    ) -> None:
        kwargs = dict(truncate_col2=truncate_col2)
        if aligned:
            return self.write_aligned_sections(sections, **kwargs)  # type: ignore
        for s in sections:
            self.write_section(s, **kwargs)  # type: ignore

    def write_aligned_sections(
        self, sections: Sequence[HelpSection], truncate_col2: bool = False
    ) -> None:
        """Writes multiple aligned definition lists."""
        all_rows = chain.from_iterable(dl.definitions for dl in sections)
        col1_width = self.compute_col1_width(all_rows, self.col1_max_width)
        for s in sections:
            self.write_section(
                s, col1_width=col1_width,
                truncate_col2=truncate_col2)

    def write_section(
        self, s: HelpSection,
        col1_width: Optional[int] = None,
        truncate_col2: bool = False,
    ) -> None:
        with self.section(s.heading):
            if s.description:
                self.write_text(s.description)
                if self.row_sep:
                    self.write(self.row_sep)
            self.write_dl(
                s.definitions, col1_width=col1_width, truncate_col2=truncate_col2)

    def write_text(self, text, style: Optional[IStyler] = None) -> None:
        if style is None or style is identity:
            return super().write_text(text)
        text_width = max(self.available_width, 11)
        lines = wrap_text(text, text_width, preserve_paragraphs=True).splitlines()
        styled_lines = indent_lines(map(style, lines), width=self.current_indent)
        wrapped_text = "\n".join(styled_lines)
        self.write(wrapped_text)
        self.write("\n")

    def compute_col1_width(self, rows: Iterable[Sequence[str]], max_width: int) -> int:
        col1_lengths = (term_len(r[0]) for r in rows)
        lengths_under_limit = (length for length in col1_lengths if length <= max_width)
        return max(lengths_under_limit, default=0)

    def write_dl(  # type: ignore
        self, rows: Sequence[Tuple[str, str]],
        col_max: Optional[int] = None,  # default changed to None wrt parent class
        col_spacing: Optional[int] = None,  # default changed to None wrt parent class
        col1_width: Optional[int] = None,
        truncate_col2: bool = False,
    ) -> None:
        """Writes a definition list into the buffer. This is how options
        and commands are usually formatted.

        If there's enough space, definition lists are rendered as a 2-column
        pseudo-table: if the first column text of a row doesn't fit in the
        provided/computed ``col1_width``, the 2nd column is printed on the
        following line.

        If the available space for the 2nd column is below ``self.col2_min_width``,
        the 2nd "column" is always printed below the 1st, indented with a minimum
        of 3 spaces (or one ``indent_increment`` if that's greater than 3).

        :param rows:
            a list of two item tuples for the terms and values.
        :param col_max:
            the maximum width for the 1st column of a definition list; this
            argument is here to not break compatibility with Click; if provided,
            it overrides the attribute ``self.col1_max_width``.
        :param col_spacing:
            number of spaces between the first and second column;
            this argument is here to not break compatibility with Click;
            if provided, it overrides ``self.col_spacing``.
        :param col1_width:
            the width to use for the first column; if not provided, it's
            computed as the length of the longest string under ``self.col1_max_width``;
            useful when you need to align multiple definition lists.
        :param truncate_col2:
            if ``True``, the text of the 2nd column is truncated to fit one line.
        """
        # |<----------------------- width ------------------------>|
        # |                |<---------- available_width ---------->|
        # | current_indent | col1_width | col_spacing | col2_width |

        col1_max_width = min(
            col_max or self.col1_max_width,
            self.available_width,
        )
        col1_width = min(
            col1_width or self.compute_col1_width(rows, col1_max_width),
            col1_max_width,
        )
        col_spacing = col_spacing or self.col_spacing
        col2_width = self.available_width - col1_width - col_spacing

        if col2_width < self.col2_min_width:
            self.write_narrow_dl(rows, truncate_col2)
        else:
            self.write_wide_dl(
                rows, col1_width, col_spacing, col2_width, truncate_col2)

    def write_wide_dl(
        self, rows: Sequence[Tuple[str, str]],
        col1_width: int, col_spacing: int, col2_width: int,
        truncate_col2: bool,
    ) -> None:

        col1_plus_spacing = col1_width + col_spacing
        col2_indentation = " " * (
            self.current_indent + max(self.indent_increment, col1_plus_spacing)
        )
        current_indentation = " " * self.current_indent

        # Use getattr to work around issue: https://github.com/python/mypy/issues/5485
        col1_styler: IStyler = getattr(self.theme, 'col1')
        col2_styler: IStyler = getattr(self.theme, 'col2')

        for first, second in iter_rows(rows, col_count=2):
            self.write(current_indentation)
            styled_first = col1_styler(first)
            self.write(styled_first)
            if not second:
                self.write('\n')
                self.write(self.row_sep)
                continue

            first_display_length = term_len(first)
            if first_display_length <= col1_width:
                spaces_to_col2 = col1_plus_spacing - first_display_length
                self.write(" " * spaces_to_col2)
            else:
                self.write("\n")
                self.write(col2_indentation)

            if truncate_col2:
                truncated = truncate_text(second, col2_width)
                styled_truncated = col2_styler(truncated)
                self.write(styled_truncated)
                self.write("\n")
            else:
                wrapped_text = wrap_text(second, col2_width, preserve_paragraphs=True)
                lines = [col2_styler(line) for line in wrapped_text.splitlines()]
                self.write(lines[0] + "\n")
                for line in lines[1:]:
                    self.write(f"{col2_indentation}{line}\n")
            if self.row_sep:
                self.write(self.row_sep)

    def write_narrow_dl(
        self, dl: Sequence[Tuple[str, str]], truncate_descr: bool = False,
    ) -> None:
        descr_extra_indent = max(3, self.indent_increment)
        descr_total_indent = self.current_indent + descr_extra_indent
        descr_max_width = self.width - descr_total_indent
        current_indentation = " " * self.current_indent
        descr_indentation = " " * descr_total_indent
        # Use getattr to work around issue: https://github.com/python/mypy/issues/5485
        col1_styler: IStyler = getattr(self.theme, 'col1')
        col2_styler: IStyler = getattr(self.theme, 'col2')

        for names, descr in iter_rows(dl, col_count=2):
            self.write(current_indentation + col1_styler(names) + '\n')
            if descr:
                if truncate_descr:
                    truncated = truncate_text(descr, descr_max_width)
                    styled_truncated = col2_styler(truncated)
                    self.write(descr_indentation + styled_truncated + "\n")
                else:
                    self.current_indent += descr_extra_indent
                    self.write_text(descr, col2_styler)
                    self.current_indent -= descr_extra_indent
            self.write("\n")
        self.buffer.pop()  # pop last newline

    def write_epilog(self, epilog):
        styled_epilog = self.theme.epilog(epilog)
        self.write(" " * self.current_indent + styled_epilog)

    def __repr__(self):
        return make_repr(
            self, width=self.width, indent_increment=self.indent_increment,
            col1_max_width=self.col1_max_width, col_spacing=self.col_spacing
        )


def truncate_text(
    text: str, max_length: int, placeholder: str = "..."
) -> str:
    text = " ".join(text.split())
    return textwrap.shorten(text, width=max_length, placeholder=placeholder)