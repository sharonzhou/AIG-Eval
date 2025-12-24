from torch.utils.cpp_extension import load

ball_query_ext = load(name="ball_query",
                      extra_include_paths=["src/include"],
                      sources=["src/ball_query_cuda.hip", "src/ball_query.cpp"],
                      verbose=True)


