# ii-to-soren's build-board image: every build, fix round, merge re-test and the engine's final
# verify run in a container started from this. The base image already has node, git, uv and the two
# agent CLIs; this adds only CPython 3.12 (inside CI's 3.11–3.14 range), installed by uv. At run time
# the container reaches the net only through the egress proxy, which does not list uv's interpreter
# download host, so creating a venv would hang fetching one. Baked in here, with downloads switched
# off, it never tries.
# Python dependencies are NOT baked in: the engine installs them at run time (before_build).
# Nothing is COPYed. Agents may not edit .claude/, so a build can never change the box it runs in.
FROM build-board/base

USER root

# A fixed, world-readable install dir (not root's home) so the unprivileged user finds it.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN uv python install 3.12 \
 && chmod -R a+rX /opt/uv-python \
 && rm -rf /root/.cache
ENV UV_PYTHON_DOWNLOADS=never

USER node
