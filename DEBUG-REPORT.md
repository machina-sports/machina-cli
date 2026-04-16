# Podcast Digest Agent Debug Report

## Issue Description
The `podcast-digest-agent` is failing to generate results and is returning an empty `digest` field along with a `workflow-status` of `"failed"`.

## Analysis Steps
1. **Agent Configuration Check:** (`machina agent get podcast-digest-agent`)
   - The agent maps the `query` input to the `podcast-digest-workflow`.

2. **Workflow Configuration Check:** (`machina workflow get podcast-digest-workflow`)
   - The workflow uses two main tasks:
     1. `search-podcasts`: Calls the `spotify-podcasts` connector using the `get-search` command to find podcasts.
     2. `generate-digest`: Calls the `google-genai` connector to create the digest using `gemini-2.5-flash` model, provided that the first task returned at least one show.
   - The `spotify-podcasts` connector expects a context variable named `$TEMP_CONTEXT_VARIABLE_SPOTIFY_BEARER_TOKEN` for its basicAuth.

3. **Execution Analysis:** (`machina execution get <execution_id>`)
   - The first task (`search-podcasts`) fails with a `task-failed` status.
   - The `workflow-error` field in the response output contains the following details:
     - **Message:** `"Authentication failed - Unauthorized access"`
     - **Code:** `401`
     - **Error Description:** 
       ```json
       {
         "error": {
           "status": 401,
           "message": "The access token expired"
         }
       }
       ```

## Root Cause
The `spotify-podcasts` connector is failing during the `search-podcasts` task because its authentication token (`SPOTIFY_BEARER_TOKEN`) has expired. This results in a 401 Unauthorized response from the Spotify API. Since no podcast shows are retrieved, the second task (`generate-digest`) doesn't execute and an empty digest is returned.

## Next Steps / Recommendations
- The Spotify bearer token needs to be refreshed or replaced.
- Update the context variable `SPOTIFY_BEARER_TOKEN` (or the underlying secret used to populate it) with a valid access token in the platform.
