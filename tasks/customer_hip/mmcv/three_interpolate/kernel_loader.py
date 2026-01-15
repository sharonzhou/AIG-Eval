from torch.utils.cpp_extension import load

interpolate_ext = load(name="three_interpolate",
                       extra_include_paths=["src/include"],
                       sources=["src/three_interpolate_cuda.hip", "src/three_interpolate.cpp"],
                       verbose=True)


