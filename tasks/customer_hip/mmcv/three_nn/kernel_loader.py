from torch.utils.cpp_extension import load

interpolate_ext = load(name="three_nn",
                       extra_include_paths=["src/include"],
                       sources=["src/three_nn_cuda.hip", "src/three_nn.cpp"],
                       verbose=True)


