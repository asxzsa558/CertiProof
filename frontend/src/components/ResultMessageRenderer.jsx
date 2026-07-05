import SingleResultMessage from './SingleResultMessage'
import MultiAssetResultMessage from './MultiAssetResultMessage'

function ResultMessageRenderer({ msg, compact = false }) {
  return msg.isMultiAsset
    ? <MultiAssetResultMessage msg={msg} compact={compact} />
    : <SingleResultMessage msg={msg} compact={compact} />
}

export { RESULT_STATES, inferResultState } from './resultRendererUtils'
export default ResultMessageRenderer
