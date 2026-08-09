/**
 * 하단 고정 네비게이션 (S1 홈 Figma 이식에서 처음 만든 것을 S5 연습 화면도
 * 그대로 써야 해서 공용 컴포넌트로 뺐다 - 마크업/계측 문구가 화면마다
 * 따로 놀지 않게 하기 위함. 탭 클릭 시 실제로 무엇을 할지(토스트를 띄울지,
 * 화면을 옮길지)는 각 화면의 onTap 이 결정한다 - 이 컴포넌트는 표시만 한다.
 */
import navHomeIcon from '../assets/home/nav_home.svg'
import navLearnIcon from '../assets/home/nav_learn.svg'
import navGrowthIcon from '../assets/home/nav_growth.svg'
import navMeIcon from '../assets/home/nav_me.svg'
import navCheckIcon from '../assets/home/nav_check.svg'

function NavItem({ itemKey, label, icon, active, onTap }) {
  return (
    <button
      type="button"
      className={`nav-item${active ? ' active' : ''}`}
      onClick={() => onTap(itemKey)}
    >
      <img src={icon} width="26" height="26" alt="" aria-hidden="true" />
      <span>{label}</span>
    </button>
  )
}

export default function BottomNav({ active, onTap }) {
  return (
    <nav className="bottom-nav" aria-label="주요 메뉴">
      <NavItem itemKey="home" label="홈" icon={navHomeIcon} active={active === 'home'} onTap={onTap} />
      <NavItem itemKey="learn" label="훈련" icon={navLearnIcon} active={active === 'learn'} onTap={onTap} />
      <span className="nav-gap" aria-hidden="true" />
      <NavItem itemKey="growth" label="성장" icon={navGrowthIcon} active={active === 'growth'} onTap={onTap} />
      <NavItem itemKey="me" label="내 정보" icon={navMeIcon} active={active === 'me'} onTap={onTap} />
      <button type="button" className="nav-fab" onClick={() => onTap('fab')}>
        <img src={navCheckIcon} width="33" height="33" alt="" aria-hidden="true" />
        <span>바로<br />확인</span>
      </button>
    </nav>
  )
}
