# The single compile standard for the iOS shader packaging chain: MSL from any source (PC chain / constant patches / in future, the Switch original translated via Ryujinx) → iphoneos metallib.
# Compile parameters are defined only once, here; the chain.metal record in the reflection json is generated from the same parameters, record == actual.
import itertools, os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../gfx/tools')); import dmsh_pch   # the precompiled header, which changes no output (so RECORD does not name it)
# -fmetal-math-mode=relaxed: keep fast math's reassociation / contraction, but forbid assuming there are no NaN / Inf. The translated shaders reproduce Maxwell's NaN semantics with isnan selects (8337 / 12809 use them),
# and the default fast mode lets each GPU's backend compiler treat them as always false; on the A20 Pro the opening course's odd frames had 727k NaN pixels in the main image (a few dozen with the same AIR on the M4 Pro), which became the black band / black-edged glow
# -fpreserve-invariance: [[invariant]] position outputs only agree across shaders with this flag (as dmsh_build.py's MAC_METAL: a depth pre-pass followed by a less-or-equal G-buffer)
# -O1: -O2's switch folding leaves a control-flow graph Apple's GPU backend can only lower slowly into very large code (as dmsh_build.py's MAC_METAL)
# -fwrapv: signed integer arithmetic wraps, as on the Switch's GPU and in SPIR-V (dmsh_build.py MAC_METAL)
METAL = ['xcrun', '-sdk', 'iphoneos', 'metal', '-c', '-O1', '-mios-version-min=18.0', '-fmetal-math-mode=relaxed', '-fpreserve-invariance', '-fwrapv']
METALLIB = ['xcrun', '-sdk', 'iphoneos', 'metallib']
RECORD = ' '.join(METAL) + '; ' + ' '.join(METALLIB)                                # Written into json chain.metal

# Brackets nested past clang's default limit of 256 ("bracket nesting level exceeded maximum of 256"): the translator opens a block for every forward branch to a common exit, so a guest
# loop unrolled with an early exit after each step nests a block a step (Ocarina of Time's agl_technique_pfx compute shaders 1f78730053feb036 and e172bd7ec218ab8e: 257, an unrolled
# 256-element walk). Only such a source compiles with DEEP: the flag only raises the limit, so the output is what the plain compile would give if it could, and the compile records
# (RECORD, dmsh_build.py MAC_RECORD) and with them every other shader's compile cache key stay as they were. The depth counts (, [ and { together, at least clang's count of any one kind
BRACKET_LIMIT, DEEP = 256, ['-fbracket-depth=1024']
_BRACKETS = bytes.maketrans(b'([{)]}', b'((()))')
_OTHERS = bytes(c for c in range(256) if c not in b'([{)]}')

def bracket_depth(msl):   # the deepest nesting of (, [ and { in the source at path msl, comments and string literals included (spirv-cross writes no brackets in them)
    with open(msl, 'rb') as f: marks = f.read().translate(_BRACKETS, _OTHERS)
    return max(itertools.accumulate(1 if c == 0x28 else -1 for c in marks), default=0)

def metal_command(metal, msl):   # the compile command for that source: DEEP added past the limit
    return [*metal, *DEEP] if bracket_depth(msl) > BRACKET_LIMIT else metal

def compile(msl, air, lib):
    dmsh_pch.compile(metal_command(METAL, msl), msl, air)
    subprocess.run([*METALLIB, air, '-o', lib], check=True)
