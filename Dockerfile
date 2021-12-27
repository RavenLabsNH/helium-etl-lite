FROM ubuntu:focal

ARG DEBIAN_FRONTEND=noninteractive
RUN apt update && apt install -y \
    git tar autoconf automake libtool build-essential \
    bzip2 bison flex cmake lz4 libsodium-dev \
    sed curl cargo python3 python3-pip vim

WORKDIR /opt/etl-lite
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Install Rust toolchain
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y


ENV CC=gcc CXX=g++ \
    PATH="/root/.cargo/bin:/opt/etl-lite/target/release:$PATH"

# Now add our code without entrypoint python script so we don't need to
# recompile blockchain node binary every time we modify entrypoint (which
# generates config on the fly)

COPY src src/
COPY migrations migrations/
COPY Cargo.toml .

# Compile code 
RUN cargo build --release

# Add entrypoint after blockchain node follower has been compiled
RUN mkdir config
COPY entrypoint.py .

ENTRYPOINT "/bin/bash"
# ENTRYPOINT ["python3", "entrypoint.py"]
# CMD ["run", "--migrate"]
