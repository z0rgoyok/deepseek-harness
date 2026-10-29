import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'

const [inputRoot, inputStage] = process.argv.slice(2)
if (!inputRoot || !inputStage) throw new Error('source root and stage are required')
const root = resolve(inputRoot)
const stage = resolve(inputStage)
const packaging = await import(pathToFileURL(root + '/scripts/executable-packaging.ts').href)
const staging = await import(pathToFileURL(root + '/scripts/build-exe-for-python-sdk-staging.ts').href)
await packaging.restoreLegacyHoists(stage, root + '/python/sdk-runtime/node_modules')
await staging.materializeStagedLinks(stage)
await staging.deduplicateStagedWorkspacePackages(stage, root)
