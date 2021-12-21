FROM ubuntu as deps-compiler
FROM ubuntu:focal

ARG DEBIAN_FRONTEND=noninteractive
RUN apt update && apt install -y \
    git tar autoconf automake libtool build-essential \
    bzip2 bison flex cmake lz4 libsodium-dev \
    sed curl cargo

# Install Rust toolchain
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

WORKDIR /opt/etl-lite

ENV CC=gcc CXX=g++ \
    PATH="/root/.cargo/bin:/opt/etl-lite/target/release:$PATH"

# Now add our code without config so we don't need to recompile every time we
# modify config
COPY src src/
COPY migrations migrations/
COPY Cargo.toml .

# Compile code 
RUN cargo build --release

# RUN DIAGNOSTIC=1 ./rebar3 as ${BUILD_TARGET} tar -v ${VERSION} -n blockchain_node \
#         && mkdir -p /opt/docker \
#         && tar -zxvf _build/${BUILD_TARGET}/rel/*/*.tar.gz -C /opt/docker
COPY config config/


#RUN ln -sf /config /opt/node/releases/$VERSION

ENTRYPOINT ["helium_etl_lite"]
CMD ["help"]
