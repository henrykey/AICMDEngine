export default {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.d.ts',
  ],
  testPathIgnorePatterns: ['/node_modules/'],
  moduleNameMapper: {
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
    '^bpmn-js/lib/Modeler$': '<rootDir>/jest.mocks/BpmnModeler.js',
  },
  transform: {
    '^.+\\.tsx?$': ['ts-jest', {
      tsconfig: {
        jsx: 'react',
        jsxFactory: 'React.createElement',
        jsxFragmentFactory: 'React.Fragment',
        esModuleInterop: true,
        allowSyntheticDefaultImports: true,
      }
    }]
  },
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
};
