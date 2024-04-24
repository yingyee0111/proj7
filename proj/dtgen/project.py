from proj.config_file import (
    ProjectConfig,
    gen_ifndef_uid,
    get_include_path,
    get_source_path,
    with_suffixes,
)
from proj.format import run_formatter
from os import PathLike
from typing import (
    TextIO,
    Sequence,
    Iterator,
    Optional,
    Union,
    Any,
    Mapping,
)
from pathlib import Path
from .struct.render import (
    render_header as render_struct_header,
    render_source as render_struct_source,
)
from .struct.spec import (
    StructSpec,
    load_spec as load_struct_spec,
)
from .enum.render import (
    render_header as render_enum_header,
    render_source as render_enum_source,
)
from .enum.spec import (
    EnumSpec,
    load_spec as load_enum_spec,
)
from .variant.spec import (
    VariantSpec,
    load_spec as load_variant_spec,
)
from .variant.render import (
    render_header as render_variant_header,
    render_source as render_variant_source,
)
from proj.hash import get_file_hash
import json

import logging

_l = logging.getLogger(__name__)

def find_files(root: Path) -> Iterator[Path]:
    patterns = ['*.struct.toml', '*.enum.toml', '*.variant.toml']
    blacklist = [
        root / 'triton',
        root / 'deps',
        root / 'build',
    ]
    
    def is_blacklisted(p: Path) -> bool:
        for blacklisted in blacklist:
            if found.is_relative_to(blacklisted):
                return True
        return False

    for pattern in patterns:
        for found in root.rglob(pattern):
            if not is_blacklisted(found):
                yield found

def render_disclaimer(spec_path: Path, root: Path, f: TextIO) -> None:
    f.write('// THIS FILE WAS AUTO-GENERATED BY proj. DO NOT MODIFY IT!\n')
    f.write('// If you would like to modify this datatype, instead modify\n')
    f.write(f'// {spec_path.relative_to(root)}\n')

def render_proj_metadata(spec_path: Path, root: Path, f: TextIO) -> None:
    _hash = get_file_hash(spec_path)
    assert _hash is not None
    proj_metadata = {'generated_from': _hash.hex()}
    f.write('/* proj-data\n')
    f.write(json.dumps(proj_metadata, sort_keys=True, indent=2))
    f.write('\n*/\n')

def _load_proj_metadata(f: TextIO) -> Optional[Mapping[str, Any]]:
    found = ''
    has_started = False
    has_finished = False
    while not has_finished:
        line = f.readline()
        if line == '':
            break
        else:
            line = line.rstrip()

        if line == '/* proj-data':
            assert not has_started
            has_started = True
        elif line == '*/' and has_started:
            has_finished = True
        elif has_started:
            found += line
    if has_finished:
        return json.loads(found)
    else:
        return None

def load_proj_metadata(p: Path) -> Optional[Mapping[str, Any]]:
    with p.open('r') as f:
        found = _load_proj_metadata(f)
    return found

def get_existing_hash(p: Path) -> Optional[bytes]:
    if not p.is_file():
        return None

    _loaded = load_proj_metadata(p)
    if _loaded is None:
        return None

    as_hex_str = _loaded.get('generated_from', None)
    if as_hex_str is None:
        return None

    return bytes.fromhex(as_hex_str)

def needs_generate_to_path(spec_path: Path, root: Path, out: Path) -> bool:
    if not out.is_file():
        return False

    current_hash = get_existing_hash(p=out)
    new_hash = get_file_hash(spec_path)
    assert new_hash is not None

    _l.debug(f'Hash diff: {new_hash!r} vs {current_hash!r}')
    return new_hash != current_hash

def generate_header(spec: Union[StructSpec, EnumSpec, VariantSpec], spec_path: Path, root: Path, out: Path, force: bool) -> bool:
    if not (force or needs_generate_to_path(spec_path=spec_path, root=root, out=out)):
        _l.info(f'No generation needed for {spec_path.relative_to(root)} -> {out.relative_to(root)}')
        return False

    _l.info(f'Regenerating {spec_path.relative_to(root)} -> {out.relative_to(root)}')

    out.parent.mkdir(exist_ok=True, parents=True)
    with out.open('w') as f:
        render_disclaimer(spec_path=spec_path, root=root, f=f)
        render_proj_metadata(spec_path=spec_path, root=root, f=f)
        ifndef = gen_ifndef_uid(out)
        f.write('\n')
        f.write(f'#ifndef {ifndef}\n')
        f.write(f'#define {ifndef}\n')
        f.write('\n')
        if isinstance(spec, StructSpec):
            render_struct_header(spec, f)
        elif isinstance(spec, VariantSpec):
            render_variant_header(spec, f)
        else:
            assert isinstance(spec, EnumSpec)
            render_enum_header(spec, f) 
        f.write('\n')
        f.write(f'#endif // {ifndef}\n')

    return True

def generate_source(spec: Union[StructSpec, EnumSpec, VariantSpec], spec_path: Path, root: Path, out: Path, force: bool) -> bool:
    if not (force or needs_generate_to_path(spec_path=spec_path, root=root, out=out)):
        _l.info(f'No generation needed for {spec_path.relative_to(root)} -> {out.relative_to(root)}')
        return False

    _l.info(f'Regenerating {spec_path.relative_to(root)} -> {out.relative_to(root)}')

    out.parent.mkdir(exist_ok=True, parents=True)
    with out.open('w') as f:
        render_disclaimer(spec_path=spec_path, root=root, f=f)
        render_proj_metadata(spec_path=spec_path, root=root, f=f)
        f.write('\n')
        f.write(f'#include "{get_include_path(out)}"\n')
        f.write('\n')
        if isinstance(spec, StructSpec):
            render_struct_source(spec, f)
        elif isinstance(spec, VariantSpec):
            render_variant_source(spec, f)
        else:
            assert isinstance(spec, EnumSpec)
            render_enum_source(spec, f) 

    return True 

def generate_files(root: Path, config: ProjectConfig, spec_path: Path, force: bool) -> Iterator[Path]:
    suffix = ''.join(spec_path.suffixes[-2:])

    spec: Union[StructSpec, EnumSpec, VariantSpec]
    if suffix == '.struct.toml':
        spec = load_struct_spec(spec_path)
    elif suffix == '.variant.toml':
        spec = load_variant_spec(spec_path)
    else:
        assert suffix == '.enum.toml'
        spec = load_enum_spec(spec_path)

    header_path = spec_path.with_suffix('').with_suffix('.dtg' + config.header_extension)
    source_path = get_source_path(header_path)

    if generate_header(spec=spec, spec_path=spec_path, root=root, out=header_path, force=force):
        yield header_path
    if generate_source(spec=spec, spec_path=spec_path, root=root, out=source_path, force=force):
        yield source_path

def run_dtgen(root: Path, config: ProjectConfig, force: bool, files: Optional[Sequence[PathLike[str]]] = None) -> None:
    if files is None:
        files = list(find_files(root))
    _l.info('Running dtgen on following files:')
    for f in files:
        _l.info(f'- {f}')
    for spec_path in files:
        generated = list(generate_files(root=root, config=config, spec_path=Path(spec_path), force=force))
        if len(generated) > 0:
            run_formatter(root, config, generated)
