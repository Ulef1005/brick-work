# API v2 reference

Every operation of the REST API at `/api/v2`, generated when the site is built from [the OpenAPI contract](../brickwork/openapi-v2.yaml), the file the app itself checks its routes against. Authentication, tokens and worked examples are in the [API v2 contract](../brickwork/api-v2.md) guide.

```python exec="on" idprefix=""
from scripts.docs_reference import api_v2
print(api_v2())
```
