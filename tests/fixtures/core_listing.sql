-- Executed only inside a randomly named schema owned by the listing test run.
CREATE TABLE documents (
    id text COLLATE "C" PRIMARY KEY CHECK (id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'),
    tenant_id text COLLATE "C" NOT NULL CHECK (tenant_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'),
    owner_id text COLLATE "C" CHECK (owner_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'),
    name text COLLATE "C" NOT NULL CHECK (
        char_length(name) BETWEEN 1 AND 256 AND octet_length(name) <= 1024
        AND name !~ ('[' || chr(1) || '-' || chr(31) || chr(127) || ']') COLLATE "C"
    ),
    score bigint NOT NULL CHECK (score BETWEEN -9007199254740991 AND 9007199254740991),
    active boolean NOT NULL
);
CREATE INDEX documents_visibility ON documents (tenant_id, owner_id, id);
