FROM python:3.13.15-slim-bookworm@sha256:3e2de9c40ca4e3d73240059f9d48baff27908f10293e985a2f382a0378e6df4a AS builder
WORKDIR /build
COPY containers/build.lock /build/build.lock
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r build.lock
COPY pyproject.toml /build/pyproject.toml
COPY src /build/src
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir /dist /build

FROM python:3.13.15-slim-bookworm@sha256:3e2de9c40ca4e3d73240059f9d48baff27908f10293e985a2f382a0378e6df4a
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
ADD --checksum=sha256:48fec46bda7f5b1638b9e959889bfbc20491247d402d120bb152687eb48143d7 https://deb.debian.org/debian/pool/main/g/gcc-12/libgomp1_12.2.0-14+deb12u1_amd64.deb /tmp/libgomp1.deb
RUN dpkg -i /tmp/libgomp1.deb && rm /tmp/libgomp1.deb
COPY containers/runtime.lock /opt/runtime/runtime.lock
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r /opt/runtime/runtime.lock
COPY --from=builder /dist /tmp/dist
RUN python -m pip install --no-deps --no-cache-dir /tmp/dist/*.whl && rm -r /tmp/dist
COPY containers/probe.py containers/healthcheck.py containers/qualification.py /opt/runtime/
RUN mkdir /model
WORKDIR /opt/runtime
USER 10001:10001
HEALTHCHECK --interval=10s --timeout=5s --start-period=90s --retries=3 CMD ["python", "/opt/runtime/healthcheck.py"]
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "-m", "ecommerce_recsys.serving"]
CMD ["--bundle-path", "/model", "--port", "8000"]
