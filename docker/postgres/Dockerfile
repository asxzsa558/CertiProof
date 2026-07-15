ARG POSTGRES_IMAGE=postgres:15-alpine
ARG AGE_VERSION=1.6.0
ARG PGVECTOR_VERSION=0.8.2

FROM ${POSTGRES_IMAGE} AS extensions-builder
ARG AGE_VERSION
ARG PGVECTOR_VERSION
RUN apk add --no-cache build-base bison flex perl readline-dev zlib-dev curl
RUN curl -fsSL "https://dlcdn.apache.org/age/PG15/${AGE_VERSION}/apache-age-${AGE_VERSION}-src.tar.gz" -o /tmp/age.tar.gz \
    && mkdir /tmp/age \
    && tar -xzf /tmp/age.tar.gz -C /tmp/age --strip-components=1 \
    && make -C /tmp/age PG_CONFIG=/usr/local/bin/pg_config with_llvm=no \
    && make -C /tmp/age PG_CONFIG=/usr/local/bin/pg_config with_llvm=no install
RUN curl -fsSL "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz" -o /tmp/pgvector.tar.gz \
    && mkdir /tmp/pgvector \
    && tar -xzf /tmp/pgvector.tar.gz -C /tmp/pgvector --strip-components=1 \
    && make -C /tmp/pgvector with_llvm=no \
    && make -C /tmp/pgvector with_llvm=no install

FROM ${POSTGRES_IMAGE}
COPY --from=extensions-builder /usr/local/lib/postgresql/ /usr/local/lib/postgresql/
COPY --from=extensions-builder /usr/local/share/postgresql/extension/ /usr/local/share/postgresql/extension/
COPY initdb/ /docker-entrypoint-initdb.d/
