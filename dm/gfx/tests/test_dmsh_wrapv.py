#!/usr/bin/env python3
"""Signed integer arithmetic in the translated shaders wraps (dmsh_build.py MAC_METAL and ios_metal.py METAL carry -fwrapv), as on the Switch's GPU and in SPIR-V: Ocarina of Time's
mesh shaders take the low half of a packed word sign-extended as (w * 65536) >> 16, in the four statements below as spirv-cross writes them. Without the flag Metal's front end took the
multiply as unable to overflow and used w's high half for the sign bits (the lightmap UV 65536 times too large: a bright band on a Deku Tree wall). On this Mac's GPU, compiled as the
build compiles, the result is the low half sign-extended for edge and random words."""
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dmsh_raw_last import MAC_METAL   # noqa: E402   the build's Mac flags, read from dmsh_build.py

IOS_TOOLS = Path(__file__).resolve().parents[2] / 'ios/tools'

KERNEL = '''#include <metal_stdlib>
using namespace metal;
kernel void k(device const uint* in [[buffer(0)]], device int* out [[buffer(1)]], uint i [[thread_position_in_grid]])
{
    int _3787 = as_type<int>(in[i]) * 65536;
    int _3823 = _3787 >> 31;
    uint _3827 = uint(_3787) >> 16u;
    out[i] = (_3823 << 16) | int(_3827);
}
'''

RUNNER = '''#import <Metal/Metal.h>
#include <stdio.h>
#include <stdlib.h>
int main(int ac, char **av) { @autoreleasepool {
    id<MTLDevice> d = MTLCreateSystemDefaultDevice(); NSError *e = nil;
    id<MTLLibrary> l = [d newLibraryWithURL:[NSURL fileURLWithPath:@(av[1])] error:&e]; if (!l) { puts(e.description.UTF8String); return 2; }
    id<MTLComputePipelineState> ps = [d newComputePipelineStateWithFunction:[l newFunctionWithName:@"k"] error:&e]; if (!ps) { puts(e.description.UTF8String); return 2; }
    int n = ac - 2; id<MTLBuffer> in = [d newBufferWithLength:n * 4 options:MTLResourceStorageModeShared], out = [d newBufferWithLength:n * 4 options:MTLResourceStorageModeShared];
    for (int i = 0; i < n; i++) ((uint32_t *)in.contents)[i] = (uint32_t)strtoul(av[i + 2], NULL, 0);
    id<MTLCommandQueue> q = [d newCommandQueue]; id<MTLCommandBuffer> c = [q commandBuffer]; id<MTLComputeCommandEncoder> ce = [c computeCommandEncoder];
    [ce setComputePipelineState:ps]; [ce setBuffer:in offset:0 atIndex:0]; [ce setBuffer:out offset:0 atIndex:1];
    [ce dispatchThreads:MTLSizeMake(n, 1, 1) threadsPerThreadgroup:MTLSizeMake(32, 1, 1)]; [ce endEncoding]; [c commit]; [c waitUntilCompleted];
    for (int i = 0; i < n; i++) printf("%d\\n", ((const int *)out.contents)[i]);
    return 0;
} }
'''


def low_half_signed(w):
    lo = w & 0xffff
    return lo - 0x10000 if lo & 0x8000 else lo


class Wrapv(unittest.TestCase):
    def test_flags(self):
        self.assertIn('-fwrapv', MAC_METAL)
        sys.path.insert(0, str(IOS_TOOLS))
        src = (IOS_TOOLS / 'ios_metal.py').read_text()
        line = next(l for l in src.splitlines() if l.startswith('METAL = '))
        self.assertIn("'-fwrapv'", line)

    @unittest.skipUnless(shutil.which('xcrun') and sys.platform == 'darwin', 'needs Metal')
    def test_sign_extension_on_gpu(self):
        rnd = random.Random(1)
        words = [0, 1, 0x7fff, 0x8000, 0xffff, 0x10000, 0x12345678, 0x8000ffff, 0xffff8000, 0x7fffffff, 0x80000000, 0xffffffff, 0x00013384, 0x00024800, 0x00037c00]
        words += [rnd.getrandbits(32) for _ in range(49)]
        with tempfile.TemporaryDirectory() as w:
            w = Path(w)
            (w / 'k.metal').write_text(KERNEL)
            r = subprocess.run(MAC_METAL + [str(w / 'k.metal'), '-o', str(w / 'k.air')], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            subprocess.run(['xcrun', '-sdk', 'macosx', 'metallib', str(w / 'k.air'), '-o', str(w / 'k.metallib')], check=True)
            (w / 'r.m').write_text(RUNNER)
            subprocess.run(['clang', '-fobjc-arc', '-framework', 'Metal', '-framework', 'Foundation', str(w / 'r.m'), '-o', str(w / 'r')], check=True, capture_output=True)
            out = subprocess.run([str(w / 'r'), str(w / 'k.metallib')] + [hex(x) for x in words], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            got = [int(x) for x in out.stdout.split()]
            bad = [(hex(x), g, low_half_signed(x)) for x, g in zip(words, got) if g != low_half_signed(x)]
            self.assertEqual(bad, [], 'word, GPU, want')


if __name__ == '__main__':
    unittest.main()
